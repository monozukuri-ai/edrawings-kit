use edrawings_core as core;
use pyo3::{
    exceptions::{PyException, PyRuntimeError, PyValueError},
    prelude::*,
    types::PyBytes,
};
use serde::Serialize;
use std::path::PathBuf;

pyo3::create_exception!(_core, NativeError, PyException);
fn map_error(e: core::Error) -> PyErr {
    match e {
        core::Error::Io(e) => e.into(),
        core::Error::Format(d) => match serde_json::to_string(&d) {
            Ok(json) => NativeError::new_err(json),
            Err(e) => PyRuntimeError::new_err(e.to_string()),
        },
    }
}
fn json<T: Serialize + ?Sized>(value: &T) -> PyResult<String> {
    serde_json::to_string(value).map_err(|e| PyRuntimeError::new_err(e.to_string()))
}
fn parse<T: serde::de::DeserializeOwned>(value: &str) -> PyResult<T> {
    serde_json::from_str(value).map_err(|e| PyValueError::new_err(e.to_string()))
}

fn user_data_policy(value: &str) -> PyResult<core::UserDataPolicy> {
    match value {
        "disabled" => Ok(core::UserDataPolicy::Disabled),
        "edrawings_first_be_v2" => Ok(core::UserDataPolicy::EdrawingsFirstBeV2),
        "edrawings_be_envelope_v1" => Ok(core::UserDataPolicy::EdrawingsBeEnvelopeV1),
        _ => Err(PyValueError::new_err(
            "user_data_profile must be 'disabled', 'edrawings_first_be_v2' or 'edrawings_be_envelope_v1'",
        )),
    }
}

fn placement_policy(value: &str) -> PyResult<core::PlacementPolicy> {
    match value {
        "verified" => Ok(core::PlacementPolicy::Verified),
        "scene_graph_v1" => Ok(core::PlacementPolicy::SceneGraphV1),
        _ => Err(PyValueError::new_err(
            "placement must be 'verified' or 'scene_graph_v1'",
        )),
    }
}

fn color_policy(value: &str) -> PyResult<core::ColorPolicy> {
    match value {
        "materials_xml" => Ok(core::ColorPolicy::MaterialsXml),
        "hsf_only" => Ok(core::ColorPolicy::HsfOnly),
        _ => Err(PyValueError::new_err(
            "colors must be 'materials_xml' or 'hsf_only'",
        )),
    }
}

fn image_policy(value: &str) -> PyResult<core::ImagePolicy> {
    match value {
        "disabled" => Ok(core::ImagePolicy::Disabled),
        "edrawings_1910_u32_v1" => Ok(core::ImagePolicy::Edrawings1910U32V1),
        _ => Err(PyValueError::new_err(
            "image_profile must be 'disabled' or 'edrawings_1910_u32_v1'",
        )),
    }
}

#[pyclass(frozen, module = "edrawings_kit._core")]
struct DocumentHandle {
    doc: core::Document,
}
#[pymethods]
impl DocumentHandle {
    #[pyo3(signature = (entry_id=None, mode="partial", user_data_profile="disabled", image_profile="disabled"))]
    fn parse_hsf(
        &self,
        py: Python<'_>,
        entry_id: Option<&str>,
        mode: &str,
        user_data_profile: &str,
        image_profile: &str,
    ) -> PyResult<HsfHandle> {
        let profiles = core::HsfProfiles {
            user_data: user_data_policy(user_data_profile)?,
            image: image_policy(image_profile)?,
        };
        let mode = match mode {
            "partial" => core::HsfMode::Partial,
            "strict" => core::HsfMode::Strict,
            _ => return Err(PyValueError::new_err("mode must be 'strict' or 'partial'")),
        };
        Ok(HsfHandle {
            doc: py
                .detach(|| self.doc.parse_hsf_with_profiles(entry_id, mode, profiles))
                .map_err(map_error)?,
        })
    }
    #[pyo3(signature = (entry_id=None, mode="partial", user_data_profile="disabled", image_profile="disabled", import_root=None, placement="verified"))]
    #[allow(clippy::too_many_arguments)]
    fn read_scene(
        &self,
        py: Python<'_>,
        entry_id: Option<&str>,
        mode: &str,
        user_data_profile: &str,
        image_profile: &str,
        import_root: Option<&str>,
        placement: &str,
    ) -> PyResult<SceneHandle> {
        let profiles = core::HsfProfiles {
            user_data: user_data_policy(user_data_profile)?,
            image: image_policy(image_profile)?,
        };
        let context = core::SceneContext {
            import_root: import_root.map(str::to_owned),
            placement: placement_policy(placement)?,
        };
        let mode = match mode {
            "partial" => core::HsfMode::Partial,
            "strict" => core::HsfMode::Strict,
            _ => return Err(PyValueError::new_err("mode must be 'strict' or 'partial'")),
        };
        Ok(SceneHandle {
            scene: py
                .detach(|| {
                    self.doc
                        .read_scene_with_context(entry_id, mode, profiles, &context)
                })
                .map_err(map_error)?,
        })
    }
    #[pyo3(signature = (entry_id=None, mode="partial", user_data_profile="disabled", image_profile="disabled", import_root=None, placement="verified"))]
    #[allow(clippy::too_many_arguments)]
    fn read_drawing(
        &self,
        py: Python<'_>,
        entry_id: Option<&str>,
        mode: &str,
        user_data_profile: &str,
        image_profile: &str,
        import_root: Option<&str>,
        placement: &str,
    ) -> PyResult<DrawingHandle> {
        let profiles = core::HsfProfiles {
            user_data: user_data_policy(user_data_profile)?,
            image: image_policy(image_profile)?,
        };
        let context = core::SceneContext {
            import_root: import_root.map(str::to_owned),
            placement: placement_policy(placement)?,
        };
        let mode = match mode {
            "partial" => core::HsfMode::Partial,
            "strict" => core::HsfMode::Strict,
            _ => return Err(PyValueError::new_err("mode must be 'strict' or 'partial'")),
        };
        Ok(DrawingHandle {
            drawing: py
                .detach(|| {
                    self.doc
                        .read_drawing_with_context(entry_id, mode, profiles, &context)
                })
                .map_err(map_error)?,
        })
    }
    #[pyo3(signature = (entry_id=None, placement="scene_graph_v1", colors="materials_xml", configuration=None, display_state=None, include_hidden=false, user_data_profile="edrawings_be_envelope_v1", image_profile="edrawings_1910_u32_v1", import_root=None))]
    #[allow(clippy::too_many_arguments)]
    fn read_display(
        &self,
        py: Python<'_>,
        entry_id: Option<&str>,
        placement: &str,
        colors: &str,
        configuration: Option<&str>,
        display_state: Option<&str>,
        include_hidden: bool,
        user_data_profile: &str,
        image_profile: &str,
        import_root: Option<&str>,
    ) -> PyResult<DisplayHandle> {
        let options = core::DisplayOptions {
            placement: placement_policy(placement)?,
            colors: color_policy(colors)?,
            configuration: configuration.map(str::to_owned),
            display_state: display_state.map(str::to_owned),
            include_hidden,
            profiles: core::HsfProfiles {
                user_data: user_data_policy(user_data_profile)?,
                image: image_policy(image_profile)?,
            },
            import_root: import_root.map(str::to_owned),
        };
        Ok(DisplayHandle {
            display: py
                .detach(|| self.doc.read_display(entry_id, &options))
                .map_err(map_error)?,
        })
    }
    fn inspection_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| json(self.doc.inspection()))
    }
    fn metadata_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| json(self.doc.metadata()))
    }
    fn extract<'py>(
        &self,
        py: Python<'py>,
        entry_id: &str,
    ) -> PyResult<(Bound<'py, PyBytes>, String)> {
        let result = py
            .detach(|| self.doc.extract(entry_id))
            .map_err(map_error)?;
        Ok((PyBytes::new(py, &result.data), json(&result.info)?))
    }
    fn verify_all_json(&self, py: Python<'_>) -> PyResult<String> {
        let results = py.detach(|| self.doc.verify_all()).map_err(map_error)?;
        json(&results)
    }
    #[pyo3(signature = (entry_id=None))]
    fn inspect_hsf_json(&self, py: Python<'_>, entry_id: Option<&str>) -> PyResult<String> {
        let result = py
            .detach(|| self.doc.inspect_hsf(entry_id))
            .map_err(map_error)?;
        json(&result)
    }
}

#[pyclass(frozen, module = "edrawings_kit._core")]
struct HsfHandle {
    doc: core::HsfDocument,
}
#[pymethods]
impl HsfHandle {
    fn summary_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| json(self.doc.summary()))
    }
    fn source_bytes<'py>(
        &self,
        py: Python<'py>,
        domain_id: &str,
        offset: u64,
        length: u64,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let bytes = self
            .doc
            .source_bytes(&core::HsfSpan {
                domain_id: domain_id.into(),
                offset,
                length,
            })
            .map_err(map_error)?;
        Ok(PyBytes::new(py, bytes))
    }
}

#[pyclass(frozen, module = "edrawings_kit._core")]
struct SceneHandle {
    scene: core::SceneResult,
}

fn words<'py>(
    py: Python<'py>,
    count: usize,
    values: impl Iterator<Item = [u8; 4]>,
) -> PyResult<Bound<'py, PyBytes>> {
    let size = count
        .checked_mul(4)
        .ok_or_else(|| PyValueError::new_err("Buffer size overflow"))?;
    PyBytes::new_with(py, size, |out| {
        for (dst, value) in out.chunks_exact_mut(4).zip(values) {
            dst.copy_from_slice(&value);
        }
        Ok(())
    })
}
#[pymethods]
impl SceneHandle {
    fn mesh_index(&self, mesh_id: &str) -> PyResult<usize> {
        self.scene.mesh_index(mesh_id).map_err(map_error)
    }
    fn shell_parameters<'py>(
        &self,
        py: Python<'py>,
        set_id: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let values = self.scene.shell_parameters(set_id).map_err(map_error)?;
        words(py, values.len(), values.iter().map(|v| v.to_le_bytes()))
    }
    fn summary_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| json(self.scene.summary()))
    }
    fn source_bytes<'py>(
        &self,
        py: Python<'py>,
        domain_id: &str,
        offset: u64,
        length: u64,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let bytes = self
            .scene
            .source_bytes(&core::HsfSpan {
                domain_id: domain_id.into(),
                offset,
                length,
            })
            .map_err(map_error)?;
        Ok(PyBytes::new(py, bytes))
    }
    fn primitive_points<'py>(
        &self,
        py: Python<'py>,
        primitive_id: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let points = self
            .scene
            .primitive_points(primitive_id)
            .map_err(map_error)?;
        words(
            py,
            points.len() * 3,
            points.iter().flatten().map(|v| v.to_le_bytes()),
        )
    }
    fn buffer<'py>(
        &self,
        py: Python<'py>,
        mesh_id: &str,
        kind: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let m = self.scene.mesh_buffers(mesh_id).map_err(map_error)?;
        match kind {
            "parameters" => words(
                py,
                m.parameters.len(),
                m.parameters.iter().map(|v| v.to_le_bytes()),
            ),
            "vertices" => words(
                py,
                m.vertices.len() * 3,
                m.vertices.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "normals" => words(
                py,
                m.normals.len() * 3,
                m.normals.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "face_list" => words(
                py,
                m.face_list.len(),
                m.face_list.iter().map(|v| v.to_le_bytes()),
            ),
            "triangles" => words(
                py,
                m.triangles.len() * 3,
                m.triangles.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "triangle_faces" => words(
                py,
                m.triangle_faces.len(),
                m.triangle_faces.iter().map(|v| v.to_le_bytes()),
            ),
            _ => Err(PyValueError::new_err("Unknown mesh buffer kind")),
        }
    }
}

fn doubles<'py>(
    py: Python<'py>,
    count: usize,
    values: impl Iterator<Item = [u8; 8]>,
) -> PyResult<Bound<'py, PyBytes>> {
    let size = count
        .checked_mul(8)
        .ok_or_else(|| PyValueError::new_err("Buffer size overflow"))?;
    PyBytes::new_with(py, size, |out| {
        for (dst, value) in out.chunks_exact_mut(8).zip(values) {
            dst.copy_from_slice(&value);
        }
        Ok(())
    })
}

#[pyclass(frozen, module = "edrawings_kit._core")]
struct DisplayHandle {
    display: core::DisplayResult,
}
#[pymethods]
impl DisplayHandle {
    fn summary_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| json(self.display.summary()))
    }
    fn body_buffer<'py>(
        &self,
        py: Python<'py>,
        index: usize,
        kind: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let b = self.display.body(index).map_err(map_error)?;
        match kind {
            "positions" => words(
                py,
                b.positions.len() * 3,
                b.positions.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "normals" => words(
                py,
                b.normals.len() * 3,
                b.normals.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "triangles" => words(
                py,
                b.triangles.len() * 3,
                b.triangles.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "edges" => words(
                py,
                b.edges.len() * 2,
                b.edges.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            _ => Err(PyValueError::new_err("Unknown body buffer kind")),
        }
    }
    fn instance_buffer<'py>(&self, py: Python<'py>, kind: &str) -> PyResult<Bound<'py, PyBytes>> {
        let i = self.display.instances();
        match kind {
            "matrices" => doubles(
                py,
                i.matrices.len() * 16,
                i.matrices.iter().flatten().map(|v| v.to_le_bytes()),
            ),
            "bodies" => words(py, i.bodies.len(), i.bodies.iter().map(|v| v.to_le_bytes())),
            "names" => words(py, i.names.len(), i.names.iter().map(|v| v.to_le_bytes())),
            "component_paths" => words(
                py,
                i.component_paths.len(),
                i.component_paths.iter().map(|v| v.to_le_bytes()),
            ),
            "colors" => PyBytes::new_with(py, i.colors.len() * 4, |out| {
                for (dst, value) in out.chunks_exact_mut(4).zip(&i.colors) {
                    dst.copy_from_slice(value);
                }
                Ok(())
            }),
            "color_sources" => Ok(PyBytes::new(py, &i.color_sources)),
            "face_visibility" => Ok(PyBytes::new(py, &i.face_visibility)),
            "visibility" => Ok(PyBytes::new(py, &i.visibility)),
            _ => Err(PyValueError::new_err("Unknown instance buffer kind")),
        }
    }
    fn preview<'py>(&self, py: Python<'py>) -> Option<(Bound<'py, PyBytes>, String)> {
        self.display
            .preview()
            .map(|(data, media)| (PyBytes::new(py, data), media.to_string()))
    }
}

#[pyclass(frozen, module = "edrawings_kit._core")]
struct DrawingHandle {
    drawing: core::DrawingResult,
}
#[pymethods]
impl DrawingHandle {
    fn summary_json(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| json(&self.drawing.summary()))
    }
    fn source_bytes<'py>(
        &self,
        py: Python<'py>,
        domain_id: &str,
        offset: u64,
        length: u64,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let bytes = self
            .drawing
            .scene()
            .source_bytes(&core::HsfSpan {
                domain_id: domain_id.into(),
                offset,
                length,
            })
            .map_err(map_error)?;
        Ok(PyBytes::new(py, bytes))
    }
    fn primitive_points<'py>(
        &self,
        py: Python<'py>,
        primitive_id: &str,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let points = self
            .drawing
            .scene()
            .primitive_points(primitive_id)
            .map_err(map_error)?;
        words(
            py,
            points.len() * 3,
            points.iter().flatten().map(|v| v.to_le_bytes()),
        )
    }
}

// PyBytes borrowing keeps the immutable owner alive while detached; no eager Vec copy
// is made before Rust has checked the input limit.
#[pyfunction]
fn probe_bytes(py: Python<'_>, data: &[u8], limits: &str) -> PyResult<String> {
    let limits = parse(limits)?;
    json(
        &py.detach(|| core::probe_bytes(data, &limits))
            .map_err(map_error)?,
    )
}
#[pyfunction]
fn probe_path(py: Python<'_>, path: PathBuf, limits: &str) -> PyResult<String> {
    let limits = parse(limits)?;
    json(
        &py.detach(|| core::probe_path(path, &limits))
            .map_err(map_error)?,
    )
}
#[pyfunction]
fn inspect_bytes(py: Python<'_>, data: &[u8], options: &str) -> PyResult<String> {
    let options = parse(options)?;
    json(
        &py.detach(|| core::inspect_bytes(data, &options))
            .map_err(map_error)?,
    )
}
#[pyfunction]
fn inspect_path(py: Python<'_>, path: PathBuf, options: &str) -> PyResult<String> {
    let options = parse(options)?;
    json(
        &py.detach(|| core::inspect_path(path, &options))
            .map_err(map_error)?,
    )
}
#[pyfunction]
fn read_bytes(py: Python<'_>, data: &[u8], options: &str) -> PyResult<DocumentHandle> {
    let options = parse(options)?;
    Ok(DocumentHandle {
        doc: py
            .detach(|| core::read_bytes(data, &options))
            .map_err(map_error)?,
    })
}
#[pyfunction]
fn read_path(py: Python<'_>, path: PathBuf, options: &str) -> PyResult<DocumentHandle> {
    let options = parse(options)?;
    Ok(DocumentHandle {
        doc: py
            .detach(|| core::read_path(path, &options))
            .map_err(map_error)?,
    })
}
#[pyfunction]
fn build_info() -> PyResult<String> {
    json(&core::build_info())
}

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<DocumentHandle>()?;
    module.add_class::<HsfHandle>()?;
    module.add_class::<SceneHandle>()?;
    module.add_class::<DrawingHandle>()?;
    module.add_class::<DisplayHandle>()?;
    module.add("NativeError", module.py().get_type::<NativeError>())?;
    module.add_function(wrap_pyfunction!(build_info, module)?)?;
    module.add_function(wrap_pyfunction!(probe_bytes, module)?)?;
    module.add_function(wrap_pyfunction!(probe_path, module)?)?;
    module.add_function(wrap_pyfunction!(inspect_bytes, module)?)?;
    module.add_function(wrap_pyfunction!(inspect_path, module)?)?;
    module.add_function(wrap_pyfunction!(read_bytes, module)?)?;
    module.add_function(wrap_pyfunction!(read_path, module)?)?;
    Ok(())
}

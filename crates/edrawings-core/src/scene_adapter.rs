use crate::hsf_adapter::{diagnostic, source, status};
use crate::*;
use std::sync::Arc;

/// Owned source domains and native arrays. JSON contains only metadata.
#[derive(Clone, Debug)]
pub struct SceneResult {
    mesh_index: std::collections::HashMap<String, usize>,
    summary: SceneSummary,
    syntax: HsfDocument,
    meshes: Vec<hsf_core::Mesh>,
    primitives: Vec<hsf_core::Primitive>,
    shell_parameter_sets: Vec<hsf_core::ShellParameterSet>,
}
pub struct MeshBuffers<'a> {
    pub parameters: &'a [f32],
    pub vertices: &'a [[f32; 3]],
    pub face_list: &'a [i32],
    pub triangles: &'a [[u32; 3]],
    pub triangle_faces: &'a [u32],
    pub normals: &'a [[f32; 3]],
}
impl SceneResult {
    pub(crate) fn update_output_usage(&mut self, budget: &hsf_core::Budget) {
        self.summary.usage.output_bytes = budget.usage().output_bytes;
    }
    pub fn shell_parameters(&self, id: &str) -> Result<&[f32], Error> {
        let i = self
            .summary
            .shell_parameter_sets
            .iter()
            .position(|s| s.id == id)
            .ok_or_else(|| {
                Error::invalid(
                    "scene.unknown_parameter_set",
                    "scene",
                    "Unknown Shell parameter set ID",
                )
            })?;
        Ok(&self.shell_parameter_sets[i].parameters)
    }
    pub fn summary(&self) -> &SceneSummary {
        &self.summary
    }
    pub fn source_bytes(&self, span: &HsfSpan) -> Result<&[u8], Error> {
        self.syntax.source_bytes(span)
    }
    pub fn primitive_points(&self, id: &str) -> Result<&[[f32; 3]], Error> {
        let i = self
            .summary
            .primitives
            .iter()
            .position(|p| p.id == id)
            .ok_or_else(|| {
                Error::invalid("scene.unknown_primitive", "scene", "Unknown primitive ID")
            })?;
        Ok(&self.primitives[i].points)
    }
    pub fn mesh_buffers(&self, id: &str) -> Result<MeshBuffers<'_>, Error> {
        let i = self.mesh_index(id)?;
        let m = &self.meshes[i];
        Ok(MeshBuffers {
            parameters: &m.parameters,
            vertices: &m.vertices,
            face_list: &m.face_list,
            triangles: &m.triangles,
            triangle_faces: &m.triangle_faces,
            normals: &m.normals,
        })
    }
    pub fn mesh_index(&self, id: &str) -> Result<usize, Error> {
        self.mesh_index
            .get(id)
            .copied()
            .ok_or_else(|| Error::invalid("scene.unknown_mesh", "scene", "Unknown mesh ID"))
    }
}
fn attr<T>(id: &str, a: Option<hsf_core::Attribute<T>>) -> Option<SceneAttribute<T>> {
    a.map(|a| SceneAttribute {
        value: a.value,
        source: source(id, a.source),
    })
}
fn vertex_parameters(id: &str, p: &hsf_core::VertexParameters) -> VertexParameters {
    VertexParameters {
        width: p.width,
        count: p.count,
        source: source(id, p.source.clone()),
        values_source: source(id, p.values_source.clone()),
        quantization: p.quantization.as_ref().map(|q| ParameterQuantization {
            bits_per_sample: q.bits_per_sample,
            packing: q.packing.clone(),
            bounds: q.bounds.clone(),
            bounds_source: source(id, q.bounds_source.clone()),
        }),
    }
}
fn line_style_element(id: &str, e: hsf_core::LineStyleElement) -> LineStyleElement {
    LineStyleElement {
        kind: e.kind,
        length: e.length,
        units: e.units,
        stretchable: e.stretchable,
        source: source(id, e.source),
        length_source: e.length_source.map(|s| source(id, s)),
        units_source: e.units_source.map(|s| source(id, s)),
    }
}
fn line_style_measure(id: &str, m: hsf_core::LineStyleMeasure) -> LineStyleMeasure {
    LineStyleMeasure {
        value: m.value,
        units: m.units,
        fixed: m.fixed,
        source: source(id, m.source),
        value_source: source(id, m.value_source),
        units_source: m.units_source.map(|s| source(id, s)),
        fixed_source: m.fixed_source.map(|s| source(id, s)),
    }
}
fn line_style_program(id: &str, p: hsf_core::LineStyleProgram) -> LineStyleProgram {
    LineStyleProgram {
        transformed_source: p.transformed_source.map(|s| source(id, s)),
        kind: p.kind,
        interpretation_status: status(p.interpretation_status),
        reason: p.reason,
        elements: p
            .elements
            .into_iter()
            .map(|e| line_style_element(id, e))
            .collect(),
        parallels: p
            .parallels
            .into_iter()
            .map(|p| LineStyleParallel {
                fit: p.fit.map(|f| LineStyleFit {
                    mode: f.mode,
                    source: source(id, f.source),
                    value_source: source(id, f.value_source),
                }),
                absolute_length_source: p.absolute_length_source.map(|s| source(id, s)),
                absolute_weight_source: p.absolute_weight_source.map(|s| source(id, s)),
                source: source(id, p.source),
                marker_source: p.marker_source.map(|s| source(id, s)),
                elements: p
                    .elements
                    .into_iter()
                    .map(|e| line_style_element(id, e))
                    .collect(),
                weight: p.weight.map(|m| line_style_measure(id, m)),
                offset: p.offset.map(|m| line_style_measure(id, m)),
                segmented_source: p.segmented_source.map(|s| source(id, s)),
            })
            .collect(),
    }
}
fn enumerated(v: hsf_core::EnumeratedValue) -> EnumeratedValue {
    EnumeratedValue {
        index: v.index,
        name: v.name,
        interpretation_status: status(v.interpretation_status),
    }
}
fn rendering_settings(id: &str, s: hsf_core::RenderingSettings) -> RenderingSettings {
    RenderingSettings {
        mask: s.mask,
        value: s.value,
        decoding_status: status(s.decoding_status),
        interpretation_status: status(s.interpretation_status),
        font_flags: s
            .font_flags
            .into_iter()
            .map(|f| FontFlag {
                name: f.name,
                bit: f.bit,
                value: f.value,
                source: source(id, f.source),
            })
            .collect(),
        operands: s
            .operands
            .into_iter()
            .map(|f| RenderingOperand {
                name: f.name,
                encoding: f.encoding,
                source: source(id, f.source),
                floats: f.floats,
                integers: f.integers,
                text: f.text.map(|t| text_value(id, t)),
                enumeration: f.enumeration.map(enumerated),
                decoding_status: status(f.decoding_status),
            })
            .collect(),
    }
}
fn glyph(id: &str, g: hsf_core::GlyphDefinition) -> GlyphDefinition {
    GlyphDefinition {
        id: format!("{id}/{}", g.id),
        source_record_id: format!("{id}/{}", g.source_record_id),
        context_node_id: format!("{id}/{}", g.context_node_id),
        source: source(id, g.source),
        name: text_value(id, g.name),
        definition_source: source(id, g.definition_source),
        interpretation_status: status(g.interpretation_status),
        reason: g.reason,
        program: g.program.map(|p| GlyphProgram {
            nominal_radius: p.nominal_radius,
            offset: p.offset,
            header_source: source(id, p.header_source),
            termination_source: source(id, p.termination_source),
            commands: p
                .commands
                .into_iter()
                .map(|c| GlyphCommand {
                    code: c.code,
                    kind: c.kind,
                    points: c.points,
                    color: c.color,
                    source: source(id, c.source),
                    payload_source: source(id, c.payload_source),
                })
                .collect(),
        }),
    }
}
pub(crate) fn read(
    extraction: Extraction,
    mode: HsfMode,
    profiles: HsfProfiles,
    context: &SceneContext,
    limits: &Limits,
    mut stages: Stages,
    budget: &mut hsf_core::Budget,
) -> Result<SceneResult, Error> {
    let id = extraction.info.entry_id.clone();
    let options = hsf_adapter::options(mode, limits, profiles.image);
    let mut scene_options = hsf_core::SceneOptions {
        mode: options.mode,
        import_root: context.import_root.clone(),
        max_meshes: limits.max_scene_meshes,
        max_primitives: limits.max_scene_primitives,
        max_nodes: limits.max_scene_nodes,
        max_instances: limits.max_scene_instances,
        max_depth: limits.max_scene_depth,
        max_visits: limits.max_scene_visits,
        max_triangles: limits.max_scene_triangles,
        max_views: limits.max_scene_views,
        max_definitions: limits.max_scene_definitions,
        inventory_user_data_record: None,
        inventory_terminal_user_data_record: None,
    };
    let context = |e: hsf_core::HsfError| Error::Format(Box::new(diagnostic(&id, *e.diagnostic)));
    let parsed = hsf_core::parse_precharged_with_user_data(
        Arc::from(extraction.data),
        &options,
        budget,
        profiles.user_data.profile(),
    )
    .map_err(context)?;
    scene_options.inventory_user_data_record = profiles.user_data.inventory_record(&parsed.data);
    scene_options.inventory_terminal_user_data_record =
        profiles.user_data.inventory_terminal_record(&parsed.data);
    let scene = hsf_core::scene(&parsed, &scene_options, budget).map_err(context)?;
    // Projection retains metadata and an independently readable HSF summary.
    let path_bytes: u64 = scene
        .data
        .instances
        .iter()
        .map(|i| &i.path)
        .chain(scene.data.primitive_instances.iter().map(|i| &i.path))
        .flatten()
        .map(|p| (p.len() + id.len() + 64) as u64)
        .sum();
    let text_bytes: u64 = scene
        .data
        .primitives
        .iter()
        .filter_map(|p| p.text.as_ref())
        .chain(scene.data.user_options.iter().map(|u| &u.text))
        .chain(scene.data.views.iter().map(|v| &v.name))
        .chain(scene.data.images.iter().map(|v| &v.name))
        .chain(
            scene
                .data
                .texture_uses
                .iter()
                .flat_map(|u| std::iter::once(&u.specification).chain(u.texture_name.iter())),
        )
        .chain(
            scene
                .data
                .line_styles
                .iter()
                .flat_map(|l| [&l.name, &l.definition]),
        )
        .chain(scene.data.fonts.iter().flat_map(|f| [&f.name, &f.lookup]))
        .chain(scene.data.textures.iter().flat_map(|t| [&t.name, &t.image]))
        .chain(
            scene
                .data
                .textures
                .iter()
                .filter_map(|t| t.options.transform_segment.as_ref()),
        )
        .chain(
            scene
                .data
                .style_segments
                .iter()
                .flat_map(|s| std::iter::once(&s.path).chain(s.condition.iter())),
        )
        .filter_map(|t| t.value.as_ref())
        .map(|s| s.len() as u64)
        .sum();
    budget
        .charge_output(
            scene
                .data
                .glyphs
                .iter()
                .map(|g| {
                    4096 + g.program.as_ref().map_or(0, |p| {
                        p.commands
                            .iter()
                            .map(|c| 1024 + c.points.len() as u64 * 32)
                            .sum::<u64>()
                    })
                })
                .sum::<u64>()
                + scene
                    .data
                    .rendering_options
                    .iter()
                    .filter_map(|o| o.settings.as_ref())
                    .map(|s| {
                        8192 + s
                            .operands
                            .iter()
                            .map(|f| 2048 + f.source.length * 8)
                            .sum::<u64>()
                    })
                    .sum::<u64>()
                + scene.data.shell_parameter_sets.len() as u64 * 4096
                + scene.data.meshes.len() as u64 * 2048
                + scene
                    .data
                    .meshes
                    .iter()
                    .map(|m| &m.owner_node_id)
                    .chain(scene.data.primitives.iter().map(|p| &p.owner_node_id))
                    .map(|owner| (128 + id.len() + owner.len()) as u64)
                    .sum::<u64>()
                + scene
                    .data
                    .meshes
                    .iter()
                    .filter_map(|m| m.entity_metadata.as_ref())
                    .flat_map(|e| &e.fields)
                    .map(|f| 1024 + f.text.value.as_ref().map_or(0, |v| v.len() as u64))
                    .sum::<u64>()
                + scene
                    .data
                    .line_styles
                    .iter()
                    .filter_map(|d| d.program.as_ref())
                    .map(|p| {
                        1024 + p.elements.len() as u64 * 1024
                            + p.parallels
                                .iter()
                                .map(|v| 4096 + v.elements.len() as u64 * 1024)
                                .sum::<u64>()
                    })
                    .sum::<u64>()
                + scene.data.textures.len() as u64 * 8192
                + 2048
                    * (parsed.data.records.len()
                        + scene.data.meshes.len()
                        + scene.data.references.len()
                        + scene.data.primitives.len()
                        + scene.data.user_options.len()
                        + scene.data.user_indices.len()) as u64
                + 8192
                    * (scene.data.nodes.len()
                        + scene.data.instances.len()
                        + scene.data.primitive_instances.len()) as u64
                + 2048
                    * (scene.data.views.len()
                        + scene.data.cameras.len()
                        + scene.data.textures.len()
                        + scene.data.images.len()
                        + scene.data.segment_aliases.len()
                        + scene.data.style_segments.len()
                        + scene.data.opaque_user_data.len()
                        + scene.data.line_styles.len()
                        + scene.data.fonts.len()
                        + scene.data.rendering_options.len()) as u64
                + 1024 * scene.data.null_shells.len() as u64
                + scene
                    .data
                    .primitives
                    .iter()
                    .map(|p| p.part_lengths.len() as u64 * 16)
                    .sum::<u64>()
                + scene
                    .data
                    .textures
                    .iter()
                    .flat_map(|t| &t.image_name_matches)
                    .map(|s| (96 + id.len() + s.len()) as u64)
                    .sum::<u64>()
                + scene.data.import_context.as_ref().map_or(0, |c| {
                    2048 + (c.requested_root.len() + c.resolved_root.len()) as u64
                        + c.context_node_ids.len() as u64 * 128
                })
                + scene
                    .data
                    .style_resolutions
                    .iter()
                    .map(|s| {
                        16384
                            + s.style_ids
                                .iter()
                                .map(|v| (128 + id.len() + v.len()) as u64)
                                .sum::<u64>()
                    })
                    .sum::<u64>()
                + scene
                    .data
                    .texture_uses
                    .iter()
                    .map(|u| {
                        8192 + u
                            .binding
                            .style_path
                            .iter()
                            .chain(&u.binding.texture_definition_ids)
                            .map(|s| (128 + id.len() + s.len()) as u64)
                            .sum::<u64>()
                    })
                    .sum::<u64>()
                + path_bytes
                + text_bytes,
        )
        .map_err(context)?;
    stages.scene = status(scene.status.clone());
    let syntax = hsf_adapter::project(parsed, extraction.info, stages)?;
    let qualify = |s: &str| format!("{id}/{s}");
    let data = scene.data;
    let summary = SceneSummary {
        shell_parameter_sets: data
            .shell_parameter_sets
            .iter()
            .map(|s| ShellParameterSet {
                mesh_id: s.mesh_id.as_ref().map(|s| qualify(s)),
                id: qualify(&s.id),
                node_id: qualify(&s.node_id),
                source_record_id: qualify(&s.source_record_id),
                source: source(&id, s.source.clone()),
                vertices_source: source(&id, s.vertices_source.clone()),
                refinement_index: s.refinement_index,
                lod: s.lod,
                target_id: s.target_id.as_ref().map(|t| qualify(t)),
                association_status: status(s.association_status.clone()),
                association_reason: s.association_reason.clone(),
                vertex_parameters: vertex_parameters(&id, &s.vertex_parameters),
                interpretation_status: status(s.interpretation_status.clone()),
            })
            .collect(),
        texture_uses: data
            .texture_uses
            .into_iter()
            .map(|u| TextureUse {
                id: qualify(&u.id),
                node_id: qualify(&u.node_id),
                source_record_id: qualify(&u.source_record_id),
                source: source(&id, u.source),
                geometry_mask: u.geometry_mask,
                specification: text_value(&id, u.specification),
                texture_name: u.texture_name.map(|t| text_value(&id, t)),
                diffuse_color: attr(&id, u.diffuse_color),
                binding: TextureBinding {
                    scope: u.binding.scope,
                    status: status(u.binding.status),
                    reason: u.binding.reason,
                    image_id: u.binding.image_id.map(|i| qualify(&i)),
                    texture_definition_ids: u
                        .binding
                        .texture_definition_ids
                        .iter()
                        .map(|i| qualify(i))
                        .collect(),
                    style_path: u.binding.style_path.iter().map(|i| qualify(i)).collect(),
                },
                interpretation_status: status(u.interpretation_status),
            })
            .collect(),
        style_resolutions: data
            .style_resolutions
            .into_iter()
            .map(|s| StyleResolution {
                node_id: qualify(&s.node_id),
                style_ids: s.style_ids.iter().map(|v| qualify(v)).collect(),
                display: s.display.map(|d| display(&id, d)),
                status: status(s.status),
                reason: s.reason,
            })
            .collect(),
        import_context: data.import_context.map(|c| SceneImportContext {
            requested_root: c.requested_root,
            resolved_root: c.resolved_root,
            node_id: qualify(&c.node_id),
            context_node_ids: c.context_node_ids.iter().map(|n| qualify(n)).collect(),
            interpretation_status: status(c.interpretation_status),
        }),
        images: data
            .images
            .into_iter()
            .map(|i| ImageDefinition {
                id: qualify(&i.id),
                node_id: qualify(&i.node_id),
                source_record_id: qualify(&i.source_record_id),
                source: source(&id, i.source),
                profile: i.profile,
                name: text_value(&id, i.name),
                position: SceneAttribute {
                    value: i.position.value,
                    source: source(&id, i.position.source),
                },
                format_options: i.format_options,
                implicit_texture_local: i.implicit_texture_local,
                width: i.width,
                height: i.height,
                compression: i.compression,
                data_source: source(&id, i.data_source),
                alpha_compression: i.alpha_compression,
                alpha_source: source(&id, i.alpha_source),
                interpretation_status: status(i.interpretation_status),
            })
            .collect(),
        segment_aliases: data
            .segment_aliases
            .into_iter()
            .map(|a| SegmentAlias {
                alias: a.alias,
                target_path: a.target_path,
                source_record_id: qualify(&a.source_record_id),
                source: source(&id, a.source),
                interpretation_status: status(a.interpretation_status),
            })
            .collect(),
        style_segments: data
            .style_segments
            .into_iter()
            .map(|s| StyleSegmentReference {
                id: qualify(&s.id),
                node_id: qualify(&s.node_id),
                target_id: s.target_id.map(|t| qualify(&t)),
                source_record_id: qualify(&s.source_record_id),
                source: source(&id, s.source),
                path: text_value(&id, s.path),
                condition: s.condition.map(|c| text_value(&id, c)),
                interpretation_status: status(s.interpretation_status),
            })
            .collect(),
        null_shells: data
            .null_shells
            .into_iter()
            .map(|a| NullShell {
                mesh_id: a.mesh_id.map(|s| qualify(&s)),
                id: qualify(&a.id),
                node_id: qualify(&a.node_id),
                source_record_id: qualify(&a.source_record_id),
                source: source(&id, a.source),
                lod: a.lod,
            })
            .collect(),
        user_indices: data
            .user_indices
            .into_iter()
            .map(|a| UserIndices {
                node_id: qualify(&a.node_id),
                source_record_id: qualify(&a.source_record_id),
                source: source(&id, a.source),
                layout: hsf_adapter::user_index(&id, a.layout),
                interpretation_status: status(a.interpretation_status),
            })
            .collect(),
        rendering_options: data
            .rendering_options
            .into_iter()
            .map(|a| RenderingOptions {
                line_style_binding: a.line_style_binding.map(|b| line_style_binding(&id, b)),
                glyph_binding: a.glyph_binding.map(|b| line_style_binding(&id, b)),
                settings: a.settings.map(|v| rendering_settings(&id, v)),
                node_id: qualify(&a.node_id),
                source_record_id: qualify(&a.source_record_id),
                source: source(&id, a.source),
                kind: a.kind,
                interpretation_status: status(a.interpretation_status),
            })
            .collect(),
        glyphs: data.glyphs.into_iter().map(|g| glyph(&id, g)).collect(),
        line_styles: data
            .line_styles
            .into_iter()
            .map(|l| LineStyleDefinition {
                program: l.program.map(|p| line_style_program(&id, p)),
                reason: l.reason,
                id: qualify(&l.id),
                source_record_id: qualify(&l.source_record_id),
                source: source(&id, l.source),
                context_node_id: qualify(&l.context_node_id),
                name: text_value(&id, l.name),
                definition: text_value(&id, l.definition),
                interpretation_status: status(l.interpretation_status),
            })
            .collect(),
        fonts: data
            .fonts
            .into_iter()
            .map(|f| FontDefinition {
                id: qualify(&f.id),
                source_record_id: qualify(&f.source_record_id),
                source: source(&id, f.source),
                context_node_id: qualify(&f.context_node_id),
                format: f.format,
                name: text_value(&id, f.name),
                encoding: f.encoding,
                lookup: text_value(&id, f.lookup),
                data_source: source(&id, f.data_source),
                interpretation_status: status(f.interpretation_status),
            })
            .collect(),
        placement_status: status(data.placement_status),
        opaque_user_data: data
            .opaque_user_data
            .into_iter()
            .map(|u| OpaqueUserData {
                source_record_id: qualify(&u.source_record_id),
                source: source(&id, u.source),
                profile: u.profile,
            })
            .collect(),
        cameras: data
            .cameras
            .into_iter()
            .map(|c| SegmentCamera {
                node_id: qualify(&c.node_id),
                source_record_id: qualify(&c.source_record_id),
                source: source(&id, c.source),
                camera_source: source(&id, c.camera_source),
                camera: camera(c.camera),
                status: status(c.status),
            })
            .collect(),
        textures: data
            .textures
            .into_iter()
            .map(|t| TextureDefinition {
                options: TextureOptions {
                    enumerations: t
                        .options
                        .enumerations
                        .into_iter()
                        .map(|e| TextureEnum {
                            name: e.name,
                            raw: e.raw,
                            value: e.value,
                            source: source(&id, e.source),
                        })
                        .collect(),
                    value_scale: attr(&id, t.options.value_scale),
                    transform_segment: t.options.transform_segment.map(|v| text_value(&id, v)),
                    parameter_offset: attr(&id, t.options.parameter_offset),
                    unevaluated_flags: t.options.unevaluated_flags,
                    decoding_status: status(t.options.decoding_status),
                },
                id: qualify(&t.id),
                source_record_id: qualify(&t.source_record_id),
                source: source(&id, t.source),
                context_node_id: qualify(&t.context_node_id),
                name: text_value(&id, t.name),
                image: text_value(&id, t.image),
                flags: t.flags,
                image_name_matches: t.image_name_matches.iter().map(|s| qualify(s)).collect(),
                interpretation_status: status(t.interpretation_status),
            })
            .collect(),
        views: data
            .views
            .into_iter()
            .map(|v| NamedView {
                id: qualify(&v.id),
                source_record_id: qualify(&v.source_record_id),
                source: source(&id, v.source),
                context_node_id: qualify(&v.context_node_id),
                name: text_value(&id, v.name),
                camera_source: source(&id, v.camera_source),
                status: status(v.status),
                camera: camera(v.camera),
            })
            .collect(),
        primitives: data
            .primitives
            .iter()
            .map(|p| PrimitiveInfo {
                id: qualify(&p.id),
                owner_node_id: qualify(&p.owner_node_id),
                kind: p.kind.clone(),
                source: source(&id, p.source.clone()),
                source_record_id: qualify(&p.source_record_id),
                points_source: source(&id, p.points_source.clone()),
                point_count: p.point_count,
                part_lengths: p.part_lengths.clone(),
                center: attr(&id, p.center.clone()),
                text: p.text.clone().map(|t| text_value(&id, t)),
            })
            .collect(),
        primitive_instances: data
            .primitive_instances
            .into_iter()
            .map(|i| PrimitiveInstance {
                world_handedness: handedness(&id, i.world_handedness),
                id: qualify(&i.id),
                primitive_id: qualify(&i.primitive_id),
                node_id: qualify(&i.node_id),
                path: i.path.iter().map(|p| qualify(p)).collect(),
                world_transform: i.world_transform,
                determinant: i.determinant,
                display: display(&id, i.display),
            })
            .collect(),
        user_options: data
            .user_options
            .into_iter()
            .map(|u| UserOptions {
                node_id: qualify(&u.node_id),
                source_record_id: qualify(&u.source_record_id),
                text: text_value(&id, u.text),
            })
            .collect(),
        hsf: syntax.summary().clone(),
        status: status(scene.status),
        units: data.units,
        processed_records: data.processed_records,
        diagnostics: scene
            .diagnostics
            .into_iter()
            .map(|d| diagnostic(&id, d))
            .collect(),
        usage: HsfUsage {
            input_bytes: budget.usage().input_bytes,
            expanded_bytes: budget.usage().expanded_bytes,
            output_bytes: budget.usage().output_bytes,
        },
        meshes: data
            .meshes
            .iter()
            .map(|m| MeshInfo {
                vertex_normals: m.vertex_normals.as_ref().map(|n| VertexNormals {
                    count: n.count,
                    source: source(&id, n.source.clone()),
                    values_source: source(&id, n.values_source.clone()),
                    encoding: n.encoding.clone(),
                    compression: n.compression,
                    bits_per_sample: n.bits_per_sample,
                    packing: n.packing.clone(),
                    bounds: n.bounds.clone(),
                }),
                entity_metadata: m.entity_metadata.as_ref().map(|e| EntityMetadata {
                    source: source(&id, e.source.clone()),
                    fields: e
                        .fields
                        .iter()
                        .map(|f| EntityMetadataField {
                            kind: f.kind.clone(),
                            text: text_value(&id, f.text.clone()),
                        })
                        .collect(),
                    decoding_status: status(e.decoding_status.clone()),
                    interpretation_status: status(e.interpretation_status.clone()),
                }),
                refinement: m.refinement.as_ref().map(|r| ShellRefinement {
                    index: r.index,
                    lod: r.lod,
                    context_node_id: qualify(&r.context_node_id),
                    target_id: qualify(&r.target_id),
                    target_node_id: qualify(&r.target_node_id),
                    application_status: status(r.application_status.clone()),
                    application_reason: r.application_reason.clone(),
                    attribute_status: status(r.attribute_status.clone()),
                }),
                vertex_parameters: m
                    .vertex_parameters
                    .as_ref()
                    .map(|p| vertex_parameters(&id, p)),
                id: qualify(&m.id),
                owner_node_id: qualify(&m.owner_node_id),
                source: source(&id, m.source.clone()),
                source_record_id: qualify(&m.source_record_id),
                vertex_count: m.vertex_count,
                face_value_count: m.face_value_count,
                triangle_count: m.triangle_count,
                normal_count: m.normal_count,
                topology: m.topology.clone(),
                triangulation: status(m.triangulation.clone()),
                bounds: m.bounds,
            })
            .collect(),
        nodes: data
            .nodes
            .into_iter()
            .map(|n| SceneNode {
                implicit: n.implicit,
                world_handedness: handedness(&id, n.world_handedness),
                display: display(&id, n.display),
                id: qualify(&n.id),
                name: n.name,
                name_source: n.name_source.map(|s| source(&id, s)),
                parent_id: n.parent_id.map(|s| qualify(&s)),
                source: n.source.map(|s| source(&id, s)),
                local_transform: attr(&id, n.local_transform),
                face_color: attr(&id, n.face_color),
                face_visible: attr(&id, n.face_visible),
            })
            .collect(),
        references: data
            .references
            .into_iter()
            .map(|r| SceneReference {
                id: qualify(&r.id),
                node_id: qualify(&r.node_id),
                target_id: r.target_id.map(|s| qualify(&s)),
                source: source(&id, r.source),
                kind: r.kind,
                transform: r.transform,
            })
            .collect(),
        instances: data
            .instances
            .into_iter()
            .map(|i| SceneInstance {
                display: display(&id, i.display),
                world_handedness: handedness(&id, i.world_handedness),
                id: qualify(&i.id),
                mesh_id: qualify(&i.mesh_id),
                node_id: qualify(&i.node_id),
                path: i.path.iter().map(|p| qualify(p)).collect(),
                world_transform: i.world_transform,
                determinant: i.determinant,
                face_color: attr(&id, i.face_color),
                face_visible: attr(&id, i.face_visible),
            })
            .collect(),
    };
    Ok(SceneResult {
        mesh_index: summary
            .meshes
            .iter()
            .enumerate()
            .map(|(i, m)| (m.id.clone(), i))
            .collect(),
        shell_parameter_sets: data.shell_parameter_sets,
        summary,
        syntax,
        meshes: data.meshes,
        primitives: data.primitives,
    })
}

fn handedness(
    id: &str,
    value: Option<hsf_core::Attribute<hsf_core::Handedness>>,
) -> Option<SceneAttribute<Handedness>> {
    value.map(|a| SceneAttribute {
        value: match a.value {
            hsf_core::Handedness::Left => Handedness::Left,
            hsf_core::Handedness::Right => Handedness::Right,
        },
        source: source(id, a.source),
    })
}

fn text_value(id: &str, t: hsf_core::TextValue) -> TextValue {
    TextValue {
        encoding: t.encoding,
        encoding_code: t.encoding_code,
        source: source(id, t.source),
        value: t.value,
        status: status(t.status),
    }
}
fn display(id: &str, d: hsf_core::DisplayAttributes) -> DisplayAttributes {
    DisplayAttributes {
        text_anchor: d.text_anchor.map(|a| SceneAttribute {
            source: source(id, a.source),
            value: enumerated(a.value),
        }),
        text_justification: d.text_justification.map(|a| SceneAttribute {
            source: source(id, a.source),
            value: enumerated(a.value),
        }),
        line_pattern: line_pattern(id, d.line_pattern),
        edge_pattern: line_pattern(id, d.edge_pattern),
        marker_symbol: d.marker_symbol.map(|a| SceneAttribute {
            source: source(id, a.source),
            value: MarkerSymbol {
                binding: a.value.binding.map(|b| line_style_binding(id, b)),
                index: a.value.index,
                name: a.value.name.map(|t| text_value(id, t)),
                symbol: a.value.symbol,
                interpretation_status: status(a.value.interpretation_status),
            },
        }),
        texture_matrix: attr(id, d.texture_matrix),
        edge_weight: d.edge_weight.map(|a| SceneAttribute {
            value: MarkerSize {
                value: a.value.value,
                units: a.value.units,
            },
            source: source(id, a.source),
        }),
        line_weight: d.line_weight.map(|a| SceneAttribute {
            value: MarkerSize {
                value: a.value.value,
                units: a.value.units,
            },
            source: source(id, a.source),
        }),
        marker_size: d.marker_size.map(|a| SceneAttribute {
            value: MarkerSize {
                value: a.value.value,
                units: a.value.units,
            },
            source: source(id, a.source),
        }),
        colors: d.colors.map(|a| attr(id, a)),
        visibility: d.visibility.map(|a| attr(id, a)),
    }
}

fn camera(c: hsf_core::Camera) -> Camera {
    Camera {
        projection_bits: c.projection_bits,
        projection: c.projection,
        stretched: c.stretched,
        position: c.position,
        target: c.target,
        up_vector: c.up_vector,
        field_width: c.field_width,
        field_height: c.field_height,
        oblique_y_degrees: c.oblique_y_degrees,
        oblique_x_degrees: c.oblique_x_degrees,
        near_limit: c.near_limit,
    }
}

fn line_pattern(
    id: &str,
    a: Option<hsf_core::Attribute<hsf_core::LinePattern>>,
) -> Option<SceneAttribute<LinePattern>> {
    a.map(|a| SceneAttribute {
        source: source(id, a.source),
        value: LinePattern {
            binding: a.value.binding.map(|b| line_style_binding(id, b)),
            index: a.value.index,
            name: a.value.name.map(|t| text_value(id, t)),
            pattern: a.value.pattern,
            cap: a.value.cap,
            join: a.value.join,
            interpretation_status: status(a.value.interpretation_status),
        },
    })
}

fn line_style_binding(id: &str, b: hsf_core::LineStyleBinding) -> LineStyleBinding {
    LineStyleBinding {
        scope: b.scope,
        definition_id: b.definition_id.map(|s| format!("{id}/{s}")),
        status: status(b.status),
        reason: b.reason,
    }
}

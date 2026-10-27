use crate::*;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
pub(crate) fn header(data: &[u8]) -> Result<Header, Error> {
    let h = hsf_core::read_header(data)?;
    Ok(Header {
        text: h.text,
        version: h.version.text,
        major: h.version.major,
        minor: h.version.minor,
        byte_len: h.byte_len,
    })
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HsfMode {
    Strict,
    #[default]
    Partial,
}

/// Owns all input and decoded domains. Byte access never reopens the input file.
#[derive(Clone, Debug)]
pub struct HsfDocument {
    summary: HsfSummary,
    domains: Vec<hsf_core::SourceDomain>,
}
impl HsfDocument {
    pub fn summary(&self) -> &HsfSummary {
        &self.summary
    }
    pub fn source_bytes(&self, span: &HsfSpan) -> Result<&[u8], Error> {
        let invalid = || {
            Error::invalid(
                "hsf.invalid_source_range",
                "source",
                "Unknown domain or out-of-bounds source range",
            )
        };
        let i = self
            .summary
            .domains
            .iter()
            .position(|d| d.id == span.domain_id)
            .ok_or_else(invalid)?;
        let end = span.offset.checked_add(span.length).ok_or_else(invalid)?;
        self.domains[i]
            .bytes()
            .get(
                usize::try_from(span.offset).map_err(|_| invalid())?
                    ..usize::try_from(end).map_err(|_| invalid())?,
            )
            .ok_or_else(invalid)
    }
}
pub(crate) fn status(value: hsf_core::Status) -> Status {
    match value {
        hsf_core::Status::NotRequested => Status::NotRequested,
        hsf_core::Status::Complete => Status::Complete,
        hsf_core::Status::Partial => Status::Partial,
        hsf_core::Status::Unsupported => Status::Unsupported,
        hsf_core::Status::Invalid => Status::Invalid,
        hsf_core::Status::LimitExceeded => Status::LimitExceeded,
    }
}
pub(crate) fn source(id: &str, value: hsf_core::SourceSpan) -> HsfSpan {
    HsfSpan {
        domain_id: format!("{id}/{}", value.domain_id),
        offset: value.offset,
        length: value.length,
    }
}
pub(crate) fn diagnostic(id: &str, value: hsf_core::Diagnostic) -> Diagnostic {
    let mut result = Diagnostic::new(
        &value.code,
        status(value.classification),
        &value.stage,
        &value.message,
    )
    .entry(id);
    result.severity = value.severity;
    if let Some(span) = value.source {
        let span = source(id, span);
        result.domain_id = Some(span.domain_id);
        result.byte_range = Some(ByteRange {
            offset: span.offset,
            length: span.length,
        });
    }
    result.opcode = value.opcode;
    result.hsf_version = value.version;
    result.impact = value.impact;
    result
}

pub(crate) fn parse(
    extraction: Extraction,
    mode: HsfMode,
    profiles: HsfProfiles,
    limits: &Limits,
    stages: Stages,
    budget: &mut hsf_core::Budget,
) -> Result<HsfDocument, Error> {
    let id = &extraction.info.entry_id;
    let options = options(mode, limits, profiles.image);
    // Extraction already charged the retained payload and outer decompression.
    let parsed = hsf_core::parse_precharged_with_user_data(
        Arc::from(extraction.data),
        &options,
        budget,
        profiles.user_data.profile(),
    )
    .map_err(|e| Error::Format(Box::new(diagnostic(id, *e.diagnostic))))?;
    project(parsed, extraction.info, stages)
}

pub(crate) fn options(
    mode: HsfMode,
    limits: &Limits,
    image: ImagePolicy,
) -> hsf_core::ParseOptions {
    hsf_core::ParseOptions {
        image_profile: image.backend(),
        max_image_pixels: limits.max_hsf_image_pixels,
        mode: match mode {
            HsfMode::Strict => hsf_core::ParseMode::Strict,
            HsfMode::Partial => hsf_core::ParseMode::Partial,
        },
        max_vertices: limits.max_hsf_vertices,
        max_face_values: limits.max_hsf_face_values,
        max_records: limits.max_hsf_records,
        max_domains: limits.max_hsf_domains,
        max_segment_depth: limits.max_hsf_segment_depth,
        max_string_bytes: limits.max_hsf_string_bytes,
        max_compression_ratio: limits.max_compression_ratio,
    }
}

pub(crate) fn project(
    parsed: hsf_core::ParseOutcome<hsf_core::HsfDocument>,
    info: ExtractionInfo,
    mut stages: Stages,
) -> Result<HsfDocument, Error> {
    let id = &info.entry_id;
    let h = parsed.data.header;
    stages.hsf_header = Status::Complete;
    stages.hsf_syntax = status(parsed.status);
    let domains = parsed
        .data
        .domains
        .iter()
        .map(|d| HsfDomain {
            id: format!("{id}/{}", d.id),
            byte_len: d.byte_len,
            sha256: d.sha256.clone(),
            parent: d.parent.clone().map(|s| source(id, s)).or_else(|| {
                Some(HsfSpan {
                    domain_id: info.source.domain_id.clone(),
                    offset: 0,
                    length: d.byte_len,
                })
            }),
            encoding: d.encoding.clone(),
            parsed_bytes: d.parsed_bytes,
        })
        .collect();
    let records = parsed
        .data
        .records
        .into_iter()
        .map(|r| HsfRecord {
            image: r.image.map(|a| ImageLayout {
                profile: a.profile,
                position: source(id, a.position),
                format_options: a.format_options,
                name: source(id, a.name),
                width: a.width,
                height: a.height,
                compression: a.compression,
                data: source(id, a.data),
                alpha_compression: a.alpha_compression,
                alpha: source(id, a.alpha),
            }),
            camera: r.camera.map(|a| CameraLayout {
                projection: a.projection,
                settings: source(id, a.settings),
            }),
            indexed_color: r.indexed_color.map(|a| IndexedColorLayout {
                geometry_mask: a.geometry_mask,
                index: a.index,
            }),
            color_map: r.color_map.map(|a| ColorMapLayout {
                format: a.format,
                entry_count: a.entry_count,
                colors: source(id, a.colors),
            }),
            texture: r.texture.map(|a| TextureLayout {
                name: source(id, a.name),
                image: source(id, a.image),
                flags: a.flags,
                fields: a
                    .fields
                    .into_iter()
                    .map(|f| OperandField {
                        name: f.name,
                        encoding: f.encoding,
                        source: source(id, f.source),
                    })
                    .collect(),
            }),
            mesh: r.mesh.map(|a| GridMeshLayout {
                flags: a.flags,
                rows: a.rows,
                columns: a.columns,
                vertex_count: a.vertex_count,
                vertices: source(id, a.vertices),
                attributes: a
                    .attributes
                    .into_iter()
                    .map(|v| GridAttributeLayout {
                        opcode: v.opcode,
                        source: source(id, v.source),
                        width: v.width,
                        bits_per_sample: v.bits_per_sample,
                        bounds: v.bounds.map(|s| source(id, s)),
                        values: source(id, v.values),
                    })
                    .collect(),
            }),
            rendering: r.rendering.map(|a| RenderingLayout {
                mask: a.mask,
                value: a.value,
                fields: a
                    .fields
                    .into_iter()
                    .map(|f| OperandField {
                        name: f.name,
                        encoding: f.encoding,
                        source: source(id, f.source),
                    })
                    .collect(),
            }),
            edge_weight: r.edge_weight.map(|a| MarkerSizeLayout {
                value_bits: a.value_bits,
                units: a.units,
            }),
            named_style: r.named_style.map(|a| NamedStyleLayout {
                index: a.index,
                name: a.name.map(|s| source(id, s)),
            }),
            clip_region: r.clip_region.map(|a| ClipRegionLayout {
                options: a.options,
                point_count: a.point_count,
                points: source(id, a.points),
            }),
            user_index: r.user_index.map(|a| user_index(id, a)),
            line_weight: r.line_weight.map(|a| MarkerSizeLayout {
                value_bits: a.value_bits,
                units: a.units,
            }),
            visibility: r.visibility.map(|v| VisibilityLayout {
                mask: v.mask,
                value: v.value,
            }),
            marker_size: r.marker_size.map(|m| MarkerSizeLayout {
                value_bits: m.value_bits,
                units: m.units,
            }),
            glyph: r.glyph.map(|l| GlyphLayout {
                name: source(id, l.name),
                definition: source(id, l.definition),
            }),
            line_style: r.line_style.map(|l| LineStyleLayout {
                name: source(id, l.name),
                definition: source(id, l.definition),
            }),
            font: r.font.map(|f| FontLayout {
                format: f.format,
                name: source(id, f.name),
                encoding: f.encoding,
                lookup: source(id, f.lookup),
                data: source(id, f.data),
            }),
            id: format!("{id}/{}", r.id),
            opcode: r.opcode,
            kind: r.kind,
            source: source(id, r.source),
            scope: r.scope.map(|s| format!("{id}/{s}")),
            payload: r.payload.map(|s| source(id, s)),
            condition: r.condition.map(|s| source(id, s)),
            value: r.value,
            view: r.view.map(|v| ViewLayout {
                projection: v.projection,
                camera: source(id, v.camera),
                name: source(id, v.name),
            }),
            user_data: r.user_data.map(|u| UserDataLayout {
                profile: u.profile,
                declared_length: u.declared_length,
                computed_payload_length: u.computed_payload_length,
                evidence_level: "empirical_corpus_layout".into(),
                native_reader_verified: false,
                fields: u
                    .fields
                    .into_iter()
                    .map(|f| UserDataField {
                        label: f.label,
                        source: source(id, f.source),
                    })
                    .collect(),
            }),
            primitive: r.primitive.map(|p| PrimitiveLayout {
                point_count: p.point_count,
                points: source(id, p.points),
                center: p.center.map(|s| source(id, s)),
                encoding: p.encoding,
                text: p.text.map(|s| source(id, s)),
                text_region: p.text_region.map(|a| TextRegionLayout {
                    options: a.options,
                    point_count: a.point_count,
                    points: source(id, a.points),
                }),
            }),
            poly_polyline: r.poly_polyline.map(|p| PolyPolylineLayout {
                flags: p.flags,
                point_count: p.point_count,
                primitive_count: p.primitive_count,
                dimensions: p.dimensions,
                lengths: source(id, p.lengths),
                points: source(id, p.points),
                leftovers: source(id, p.leftovers),
            }),
            shell: r.shell.map(|s| ShellLayout {
                null: s.null,
                flags: s.flags,
                extended_flags: s.extended_flags,
                refinement_index: s.refinement_index,
                lod: s.lod,
                vertex_count: s.vertex_count,
                vertices: source(id, s.vertices),
                face_value_count: s.face_value_count,
                face_bits: s.face_bits,
                faces: source(id, s.faces),
                normals: s.normals.map(|s| source(id, s)),
                attributes: s
                    .attributes
                    .into_iter()
                    .map(|a| ShellAttributeLayout {
                        opcode: a.opcode,
                        source: source(id, a.source),
                        fields: a
                            .fields
                            .into_iter()
                            .map(|f| OperandField {
                                name: f.name,
                                encoding: f.encoding,
                                source: source(id, f.source),
                            })
                            .collect(),
                    })
                    .collect(),
            }),
        })
        .collect();
    Ok(HsfDocument {
        domains: parsed.data.domains,
        summary: HsfSummary {
            entry_id: id.clone(),
            header: Header {
                text: h.text,
                version: h.version.text,
                major: h.version.major,
                minor: h.version.minor,
                byte_len: h.byte_len,
            },
            stages,
            source: info.source,
            records,
            domains,
            unparsed: parsed.unparsed.into_iter().map(|s| source(id, s)).collect(),
            diagnostics: parsed
                .diagnostics
                .into_iter()
                .map(|d| diagnostic(id, d))
                .collect(),
            usage: HsfUsage {
                input_bytes: parsed.usage.input_bytes,
                expanded_bytes: parsed.usage.expanded_bytes,
                output_bytes: parsed.usage.output_bytes,
            },
        },
    })
}

pub(crate) fn user_index(id: &str, a: hsf_core::UserIndexLayout) -> UserIndexLayout {
    UserIndexLayout {
        count: a.count,
        indices: source(id, a.indices),
        values: source(id, a.values),
    }
}

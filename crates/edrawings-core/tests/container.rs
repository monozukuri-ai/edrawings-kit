use edrawings_core::*;

const HSF: &[u8] = b";; HSF V19.10 \nI\x04\0\0\0";
fn push16(out: &mut Vec<u8>, v: u16) {
    out.extend(v.to_le_bytes());
}
fn push32(out: &mut Vec<u8>, v: u32) {
    out.extend(v.to_le_bytes());
}

/// Independently constructs the documented classic ZIP records for contract tests.
fn zip(entries: &[(&str, &[u8])], prefix: bool) -> Vec<u8> {
    let mut data = Vec::new();
    let mut central = Vec::new();
    for (name, bytes) in entries {
        let offset = data.len() as u32;
        data.extend(b"PK\x03\x04");
        for n in [20, 0, 0, 0, 0] {
            push16(&mut data, n);
        }
        for n in [
            crc32fast::hash(bytes),
            bytes.len() as u32,
            bytes.len() as u32,
        ] {
            push32(&mut data, n);
        }
        push16(&mut data, name.len() as u16);
        push16(&mut data, 0);
        data.extend(name.as_bytes());
        data.extend(*bytes);
        central.extend(b"PK\x01\x02");
        for n in [20, 20, 0, 0, 0, 0] {
            push16(&mut central, n);
        }
        for n in [
            crc32fast::hash(bytes),
            bytes.len() as u32,
            bytes.len() as u32,
        ] {
            push32(&mut central, n);
        }
        for n in [name.len() as u16, 0, 0, 0, 0] {
            push16(&mut central, n);
        }
        push32(&mut central, 0);
        push32(&mut central, offset);
        central.extend(name.as_bytes());
    }
    let offset = data.len() as u32;
    let size = central.len() as u32;
    data.extend(central);
    data.extend(b"PK\x05\x06");
    for n in [0, 0, entries.len() as u16, entries.len() as u16] {
        push16(&mut data, n);
    }
    push32(&mut data, size);
    push32(&mut data, offset);
    push16(&mut data, 0);
    if prefix {
        let mut p = b"[\x01\0\0\0\xbe\r2008+ archive".to_vec();
        p.resize(88, 0);
        p.extend([255, 255, 255, 127]);
        p.extend(data);
        p
    } else {
        data
    }
}
fn code(error: Error) -> String {
    error.diagnostic().unwrap().code.clone()
}

fn zlib(bytes: &[u8]) -> Vec<u8> {
    use std::io::Write;
    let mut encoder = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
    encoder.write_all(bytes).unwrap();
    encoder.finish().unwrap()
}

fn localize(value: &mut serde_json::Value, prefix: &str) {
    match value {
        serde_json::Value::String(s) => {
            if let Some(local) = s.strip_prefix(prefix) {
                *s = local.to_owned();
            }
        }
        serde_json::Value::Array(a) => a.iter_mut().for_each(|v| localize(v, prefix)),
        serde_json::Value::Object(o) => o.values_mut().for_each(|v| localize(v, prefix)),
        _ => {}
    }
}

fn compare_hsf_direct(doc: &Document, id: &str) {
    let payload = doc.extract(id).unwrap().data;
    let direct = hsf_core::parse(
        &payload,
        &hsf_core::ParseOptions::default(),
        &mut hsf_core::Budget::new(hsf_core::Limits::default()),
    )
    .unwrap();
    let parsed = doc.parse_hsf(Some(id), HsfMode::Partial).unwrap();
    let result = parsed.summary();
    let mut records = serde_json::to_value(&result.records).unwrap();
    localize(&mut records, &format!("{id}/"));
    assert_eq!(records, serde_json::to_value(&direct.data.records).unwrap());
    let mut unparsed = serde_json::to_value(&result.unparsed).unwrap();
    localize(&mut unparsed, &format!("{id}/"));
    assert_eq!(unparsed, serde_json::to_value(&direct.unparsed).unwrap());
    assert_eq!(
        serde_json::to_value(result.stages.hsf_syntax).unwrap(),
        serde_json::to_value(direct.status).unwrap()
    );
    assert_eq!(result.stages.scene, Status::NotRequested);
    assert_eq!(result.source.payload_sha256, sha256(&payload));
    for (domain, original) in result.domains.iter().zip(&direct.data.domains) {
        assert_eq!(domain.sha256, original.sha256);
        assert_eq!(domain.parsed_bytes, original.parsed_bytes);
        assert_eq!(
            parsed
                .source_bytes(&HsfSpan {
                    domain_id: domain.id.clone(),
                    offset: 0,
                    length: domain.byte_len
                })
                .unwrap(),
            original.bytes()
        );
        if original.parent.is_some() {
            let parent = parsed
                .source_bytes(domain.parent.as_ref().unwrap())
                .unwrap();
            assert_eq!(
                parent,
                direct
                    .data
                    .source_bytes(original.parent.as_ref().unwrap())
                    .unwrap()
            );
        }
    }
    assert_eq!(
        result.domains[0].parent.as_ref().unwrap().domain_id,
        result.source.domain_id
    );
    assert_eq!(result.diagnostics.len(), direct.diagnostics.len());
    for (actual, expected) in result.diagnostics.iter().zip(&direct.diagnostics) {
        let span = expected.source.as_ref().unwrap();
        assert_eq!(actual.code, expected.code);
        assert_eq!(actual.opcode, expected.opcode);
        assert_eq!(actual.hsf_version, expected.version);
        assert_eq!(
            actual.domain_id.as_deref(),
            Some(format!("{id}/{}", span.domain_id).as_str())
        );
        assert_eq!(actual.byte_range.as_ref().unwrap().offset, span.offset);
        let error = doc.parse_hsf(Some(id), HsfMode::Strict).unwrap_err();
        assert_eq!(error.diagnostic().unwrap(), actual);
    }
}

#[test]
fn m2_direct_backend_and_three_wrappers_agree() {
    for decoded in [b"(\x01aU\x03\0k=v)z".as_slice(), b";ok\n\xfeI\0\0\0\0z"] {
        let payload = [
            b";; HSF V19.10 \nI\x04\0\0\0Z".as_slice(),
            &zlib(decoded),
            b"\0",
        ]
        .concat();
        for raw in [
            payload.clone(),
            zip(&[("eModel", &payload)], false),
            zip(&[("eModel", &payload)], true),
        ] {
            let doc = read_bytes(&raw, &ReadOptions::default()).unwrap();
            compare_hsf_direct(&doc, &doc.inspection().hsf_candidates[0]);
        }
    }
}

#[test]
fn m2_entry_ids_namespace_records_domains_and_errors() {
    let payload = [HSF, b"Z", &zlib(b";ok\n\xfez"), b"\0"].concat();
    let raw = zip(&[("eModel", &payload), ("eModel", &payload)], false);
    let doc = read_bytes(&raw, &ReadOptions::default()).unwrap();
    assert_eq!(
        code(doc.parse_hsf(None, HsfMode::Partial).unwrap_err()),
        "hsf.ambiguous_candidates"
    );
    let a = doc.parse_hsf(Some("entry:0"), HsfMode::Partial).unwrap();
    let b = doc.parse_hsf(Some("entry:1"), HsfMode::Partial).unwrap();
    assert_ne!(a.summary().records[0].id, b.summary().records[0].id);
    assert_ne!(a.summary().domains[1].id, b.summary().domains[1].id);
    assert_ne!(
        a.summary().diagnostics[0].domain_id,
        b.summary().diagnostics[0].domain_id
    );
    assert_eq!(
        a.summary().diagnostics[0].byte_range,
        b.summary().diagnostics[0].byte_range
    );
    assert!(a.source_bytes(&b.summary().records[0].source).is_err());
    assert!(
        a.source_bytes(&HsfSpan {
            domain_id: a.summary().domains[0].id.clone(),
            offset: u64::MAX,
            length: 1
        })
        .is_err()
    );
    compare_hsf_direct(&doc, "entry:1");
}

#[test]
fn m2_outer_and_inner_decompression_use_one_budget() {
    let decoded = [b";".as_slice(), &[b'x'; 58], b"\nz"].concat();
    let payload = [HSF, b"Z", &zlib(&decoded), b"\0"].concat();
    let raw = zip(&[("eModel", &payload)], false);
    let options = ReadOptions {
        limits: Limits {
            max_expanded_bytes: (payload.len() + decoded.len() - 1) as u64,
            ..Default::default()
        },
        ..Default::default()
    };
    let doc = read_bytes(&raw, &options).unwrap();
    let e = doc.parse_hsf(None, HsfMode::Partial).unwrap_err();
    let d = e.diagnostic().unwrap();
    assert_eq!(d.code, "budget.expanded");
    assert_eq!(d.entry_id.as_deref(), Some("entry:0"));
    assert_eq!(d.domain_id.as_deref(), Some("entry:0/hsf:0"));
    assert_eq!(d.opcode, Some(b'Z'));
    let options = ReadOptions {
        limits: Limits {
            max_expanded_bytes: (payload.len() + decoded.len()) as u64,
            ..Default::default()
        },
        ..Default::default()
    };
    let doc = read_bytes(&raw, &options).unwrap();
    let parsed = doc.parse_hsf(None, HsfMode::Strict).unwrap();
    assert_eq!(
        parsed.summary().usage.expanded_bytes,
        (payload.len() + decoded.len()) as u64
    );
}

#[test]
fn direct_and_wrapped_hsf_agree_and_domains_differ() {
    let mut headers = vec![];
    for input in [
        HSF.to_vec(),
        zip(&[("eModel", HSF)], false),
        zip(&[("eModel", HSF)], true),
    ] {
        let doc = read_bytes(&input, &ReadOptions::default()).unwrap();
        let h = doc.inspect_hsf(None).unwrap();
        headers.push(serde_json::to_value(h.header).unwrap());
        assert_eq!(h.syntax_status, Status::NotRequested);
        assert_eq!(h.source.decoded_range.offset, 0);
        assert_eq!(h.source.payload_sha256, sha256(HSF));
        if doc.inspection().prefix_bytes > 0 {
            assert_eq!(h.source.container_range.offset, 128);
            assert_eq!(doc.inspection().zip_offset_base, Some(92));
        }
    }
    assert_eq!(headers[0], headers[1]);
    assert_eq!(headers[1], headers[2]);
}
#[test]
fn duplicate_names_are_distinct_and_selection_is_explicit() {
    let bytes = zip(
        &[
            ("eModel", HSF),
            ("eModel", HSF),
            ("../unknown", b"untouched"),
        ],
        false,
    );
    let doc = read_bytes(&bytes, &ReadOptions::default()).unwrap();
    assert_eq!(doc.inspection().entries.len(), 3);
    assert_eq!(
        code(doc.inspect_hsf(None).unwrap_err()),
        "hsf.ambiguous_candidates"
    );
    assert_eq!(doc.extract("entry:2").unwrap().data, b"untouched");
    assert!(doc.inspect_hsf(Some("entry:1")).is_ok());
}
#[test]
fn crc_is_lazy_and_damage_never_returns_empty_success() {
    let mut data = zip(&[("eModel", HSF)], false);
    data[36] ^= 1;
    let doc = read_bytes(&data, &ReadOptions::default()).unwrap();
    assert_eq!(doc.inspection().entries[0].crc_status, "not_checked");
    assert_eq!(
        code(doc.extract("entry:0").unwrap_err()),
        "zip.crc_mismatch"
    );
    let options = ReadOptions {
        verify_all: true,
        ..Default::default()
    };
    assert_eq!(
        code(read_bytes(&data, &options).unwrap_err()),
        "zip.crc_mismatch"
    );
}
#[test]
fn limits_apply_before_extract_and_across_entries() {
    let data = zip(&[("one", b"123456"), ("two", b"abcdef")], false);
    let options = ReadOptions {
        limits: Limits {
            max_expanded_bytes: 10,
            ..Limits::default()
        },
        ..Default::default()
    };
    let doc = read_bytes(&data, &options).unwrap();
    assert!(doc.extract("entry:0").is_ok());
    assert!(doc.extract("entry:1").is_ok());
    assert_eq!(code(doc.verify_all().unwrap_err()), "budget.expanded");
    assert!(
        inspect_bytes(
            &data,
            &InspectOptions {
                limits: Limits {
                    max_entries: 1,
                    ..Limits::default()
                },
                ..Default::default()
            }
        )
        .is_err()
    );
    assert!(
        read_bytes(
            &data,
            &ReadOptions {
                limits: Limits {
                    max_output_bytes: 0,
                    ..Limits::default()
                },
                ..Default::default()
            }
        )
        .is_err()
    );
}
#[test]
fn generic_zip_has_no_document_kind_or_hsf_claim() {
    let data = zip(&[("file.txt", b"hello")], false);
    let i = inspect_bytes(
        &data,
        &InspectOptions {
            filename: Some("fake.eprt".into()),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(i.document_kind, "unknown");
    assert!(i.hsf_candidates.is_empty());
    assert_eq!(
        code(
            read_bytes(&data, &ReadOptions::default())
                .unwrap()
                .inspect_hsf(None)
                .unwrap_err()
        ),
        "hsf.no_candidate"
    );
}
#[test]
fn every_truncated_zip_prefix_is_rejected_without_panicking() {
    let data = zip(&[("eModel", HSF)], true);
    for n in 0..data.len() {
        assert!(
            inspect_bytes(&data[..n], &InspectOptions::default()).is_err(),
            "{n}"
        );
    }
}
#[test]
fn local_central_mismatch_and_zip64_are_explicit() {
    let mut data = zip(&[("eModel", HSF)], false);
    data[14] ^= 1;
    assert_eq!(
        code(inspect_bytes(&data, &InspectOptions::default()).unwrap_err()),
        "zip.invalid_structure"
    );
    let mut data = zip(&[("eModel", HSF)], false);
    let at = data.len() - 22 + 10;
    data[at..at + 2].copy_from_slice(&u16::MAX.to_le_bytes());
    assert_eq!(
        code(inspect_bytes(&data, &InspectOptions::default()).unwrap_err()),
        "zip.zip64"
    );
}
#[test]
fn metadata_is_structural_only_and_can_be_disabled() {
    let data = zip(
        &[(
            "scene.xml",
            b"<?xml version=\"1.0\"?><scene><node/></scene>",
        )],
        false,
    );
    let doc = read_bytes(&data, &ReadOptions::default()).unwrap();
    assert_eq!(doc.metadata()[0].root_name, "scene");
    assert_eq!(doc.metadata()[0].elements, 2);
    assert_eq!(doc.metadata()[0].semantic_status, Status::NotRequested);
    let bad = zip(&[("scene.xml", b"<a></b>")], false);
    assert!(read_bytes(&bad, &ReadOptions::default()).is_err());
    assert!(
        read_bytes(
            &bad,
            &ReadOptions {
                read_metadata: false,
                ..Default::default()
            }
        )
        .is_ok()
    );
    let dtd = zip(
        &[(
            "scene.xml",
            b"<!DOCTYPE a [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><a>&x;</a>",
        )],
        false,
    );
    assert_eq!(
        code(read_bytes(&dtd, &ReadOptions::default()).unwrap_err()),
        "xml.dtd"
    );
}

#[test]
fn m3_direct_backend_and_wrapped_scenes_agree() {
    let mut body = b"(\x04part~\x01\xff\0\0S\x10\0".to_vec();
    body.extend(3i32.to_le_bytes());
    for v in [0f32, 0., 0., 2., 0., 0., 0., 3., 0.] {
        body.extend(v.to_le_bytes());
    }
    body.extend(b"\x01\x05\0\0\0\x08\x03\0\x01\x02q)(\x05place%");
    for v in [1f32, 0., 0., 0., 1., 0., 0., 0., 1., 10., 20., 30.] {
        body.extend(v.to_le_bytes());
    }
    body.extend(b"r\0\0\0\0)z");
    let raw = [b";; HSF V19.10 \nZ".as_slice(), &zlib(&body), b"\0"].concat();
    let mut budget = hsf_core::Budget::new(hsf_core::Limits::default());
    let parsed = hsf_core::parse(&raw, &hsf_core::ParseOptions::default(), &mut budget).unwrap();
    let direct = hsf_core::scene(&parsed, &hsf_core::SceneOptions::default(), &mut budget).unwrap();
    let expected = serde_json::to_value(&direct.data).unwrap();
    for (data, id) in [
        (raw.clone(), "raw:0"),
        (zip(&[("eModel", &raw)], false), "entry:0"),
        (zip(&[("eModel", &raw)], true), "entry:0"),
    ] {
        let scene = read_bytes(&data, &ReadOptions::default())
            .unwrap()
            .read_scene(None, HsfMode::Strict)
            .unwrap();
        let summary = scene.summary();
        assert_eq!(summary.status, Status::Complete);
        let mut actual = serde_json::to_value(summary).unwrap();
        localize(&mut actual, &format!("{id}/"));
        for key in [
            "meshes",
            "nodes",
            "references",
            "instances",
            "processed_records",
            "units",
        ] {
            assert_eq!(actual[key], expected[key], "{key}");
        }
        let buffers = scene.mesh_buffers(&summary.meshes[0].id).unwrap();
        assert_eq!(buffers.vertices, direct.data.meshes[0].vertices);
        assert_eq!(buffers.triangles, direct.data.meshes[0].triangles);
        assert_eq!(buffers.triangle_faces, direct.data.meshes[0].triangle_faces);
        assert_eq!(buffers.face_list, direct.data.meshes[0].face_list);
        assert_eq!(
            summary.usage.expanded_bytes,
            (body.len() + raw.len()) as u64
        );
        assert!(summary.usage.output_bytes > summary.hsf.usage.output_bytes);
    }
}

#[test]
fn m4_direct_backend_and_wrapped_drawing_primitives_agree() {
    let mut body = b"(\x01a~\x14\x01\x02\x03V\x14\x04l".to_vec();
    for v in [0f32, 0., 2., 3., 4., 2.] {
        body.extend(v.to_le_bytes());
    }
    body.push(b'x');
    for v in [1f32, 2., 2.] {
        body.extend(v.to_le_bytes());
    }
    let label: Vec<u8> = "寸法 10"
        .encode_utf16()
        .flat_map(|v| v.to_le_bytes())
        .collect();
    body.extend([5, label.len() as u8]);
    body.extend(&label);
    body.push(0);
    body.push(0x16);
    body.extend(((label.len() / 2) as u16).to_le_bytes());
    body.extend(&label);
    body.extend(b")q(\x01br\0\0\0\0)z");
    let raw = [b";; HSF V19.10 \nZ".as_slice(), &zlib(&body), b"\0"].concat();
    let mut budget = hsf_core::Budget::new(hsf_core::Limits::default());
    let parsed = hsf_core::parse(&raw, &hsf_core::ParseOptions::default(), &mut budget).unwrap();
    let direct = hsf_core::scene(&parsed, &hsf_core::SceneOptions::default(), &mut budget).unwrap();
    let expected = serde_json::to_value(&direct.data).unwrap();
    for (data, id) in [
        (raw.clone(), "raw:0"),
        (zip(&[("eModel", &raw)], false), "entry:0"),
        (zip(&[("eModel", &raw)], true), "entry:0"),
    ] {
        let doc = read_bytes(&data, &ReadOptions::default()).unwrap();
        let drawing = doc.read_drawing(None, HsfMode::Partial).unwrap();
        let summary = drawing.summary();
        assert_eq!(summary.scene.status, Status::Complete);
        assert_eq!(summary.assessment.status, Status::Partial);
        assert_eq!(summary.assessment.dimension_status, Status::Unsupported);
        let mut actual = serde_json::to_value(summary.scene).unwrap();
        localize(&mut actual, &format!("{id}/"));
        for key in [
            "primitives",
            "primitive_instances",
            "user_options",
            "nodes",
            "references",
            "processed_records",
        ] {
            assert_eq!(actual[key], expected[key], "{key}");
        }
        for (p, d) in summary.scene.primitives.iter().zip(&direct.data.primitives) {
            assert_eq!(drawing.scene().primitive_points(&p.id).unwrap(), d.points);
            assert_eq!(
                drawing.scene().source_bytes(&p.points_source).unwrap(),
                parsed.data.source_bytes(&d.points_source).unwrap()
            );
        }
        assert_eq!(
            code(doc.read_drawing(None, HsfMode::Strict).unwrap_err()),
            "drawing.document_semantics_unverified"
        );
    }
}

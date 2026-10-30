use edrawings_core::*;
use flate2::{Compression, write::ZlibEncoder};
use std::io::Write;

// Invented wire bytes with embedded ']' decoys. No dependency on the profile's
// cursor, length calculator, or research Python implementation.
fn block(revision: u32, include: &[u8], delta: u32) -> Vec<u8> {
    fn blob(out: &mut Vec<u8>, b: &[u8]) {
        out.push(b.len() as u8);
        out.extend(b);
    }
    let mut p = vec![0xbe];
    for s in [b"]h\0".as_slice(), b"writer", b"", b"\xff"] {
        blob(&mut p, s);
    }
    p.push(1);
    p.extend([0; 64]);
    p.extend(revision.to_le_bytes());
    p.push(0);
    p.extend([b']'; 16]);
    blob(&mut p, include);
    blob(&mut p, &[0; 16]);
    blob(&mut p, &[0; 16]);
    blob(&mut p, b"config");
    p.extend([0, 1]);
    blob(&mut p, format!("{revision};").as_bytes());
    p.push(0);
    blob(&mut p, &[b']'; 24]);
    p.extend(vec![0; if revision == 22 { 4 } else { 48 }]);
    let mut out = vec![b'['];
    out.extend((p.len() as u32 - delta).to_le_bytes());
    out.extend(p);
    out.push(b']');
    out
}
fn file(version: &str, body: &[u8], prefix: &[u8]) -> Vec<u8> {
    let mut out = format!(";; HSF V{version} \n").into_bytes();
    out.extend(prefix);
    out.push(b'Z');
    let mut z = ZlibEncoder::new(Vec::new(), Compression::default());
    z.write_all(body).unwrap();
    out.extend(z.finish().unwrap());
    out.push(0);
    out
}
fn root() -> Vec<u8> {
    let mut p = b"I\x04\0\0\0B\0".to_vec();
    for f in [-1f32, -1., -1., 1., 1., 1.] {
        p.extend(f.to_le_bytes());
    }
    p
}
fn doc(data: &[u8]) -> Document {
    read_bytes(data, &ReadOptions::default()).unwrap()
}
fn parse(d: &Document) -> HsfDocument {
    d.parse_hsf_with_user_data(None, HsfMode::Partial, UserDataPolicy::EdrawingsFirstBeV2)
        .unwrap()
}
#[test]
fn profiles_preserve_fields_and_continue_only_from_computed_end() {
    for (version, revision) in [
        ("8.05", 22),
        ("14.50", 39),
        ("19.10", 45),
        ("19.10", 46),
        ("19.10", 47),
        ("19.10", 48),
        ("19.10", 51),
    ] {
        for include in [b"".as_slice(), b"/include/test"] {
            let delta = 1 + u32::from(include.is_empty());
            let header = block(revision, include, delta);
            let mut body = header.clone();
            body.extend(b"U\x03\0x=yz");
            let d = doc(&file(version, &body, &root()));
            let p = parse(&d);
            let s = p.summary();
            assert_eq!(s.stages.hsf_syntax, Status::Partial);
            assert!(s.unparsed.is_empty()); // Coverage does not erase inference.
            assert_eq!(s.diagnostics.len(), 1);
            assert_eq!(s.diagnostics[0].code, "hsf.experimental_user_data");
            let r = &s.records[3];
            assert_eq!(p.source_bytes(&r.source).unwrap(), header);
            let u = r.user_data.as_ref().unwrap();
            assert_eq!(u.computed_payload_length - u.declared_length, delta);
            assert!(!u.native_reader_verified);
            let mut at = 0;
            for f in &u.fields {
                assert_eq!(f.source.offset, at);
                assert_eq!(f.source.domain_id, r.source.domain_id);
                at += f.source.length;
                assert_eq!(
                    p.source_bytes(&f.source).unwrap().len() as u64,
                    f.source.length
                );
            }
            assert_eq!(at, header.len() as u64);
            assert_eq!(s.records[4].source.offset, at);
            assert_eq!(s.records[4].kind, "user_options");
            assert_eq!(
                d.parse_hsf(None, HsfMode::Partial)
                    .unwrap()
                    .summary()
                    .domains[1]
                    .parsed_bytes,
                0
            );
            let e = d
                .parse_hsf_with_user_data(None, HsfMode::Strict, UserDataPolicy::EdrawingsFirstBeV2)
                .unwrap_err();
            assert!(e.to_string().contains("hsf.experimental_user_data"));
            let scene = d
                .read_scene_with_user_data(
                    None,
                    HsfMode::Partial,
                    UserDataPolicy::EdrawingsFirstBeV2,
                )
                .unwrap();
            assert!(scene.summary().instances.is_empty());
            assert!(
                scene
                    .summary()
                    .diagnostics
                    .iter()
                    .any(|d| d.code == "hsf.user_data_semantics")
            );
        }
    }
}
#[test]
fn all_truncations_and_false_boundaries_stop_without_resync() {
    let b = block(46, b"", 2);
    for n in 0..b.len() {
        let d = doc(&file("19.10", &b[..n], &root()));
        match d.parse_hsf_with_user_data(None, HsfMode::Partial, UserDataPolicy::EdrawingsFirstBeV2)
        {
            Ok(p) => {
                assert_eq!(p.summary().domains[1].parsed_bytes, 0);
                assert_eq!(p.summary().records.len(), 3);
            }
            Err(e) => assert!(n == 0 && e.to_string().contains("missing_terminator")),
        }
    }
    let mut wrong_stop = b.clone();
    *wrong_stop.last_mut().unwrap() = b'!';
    for mut bad in [
        wrong_stop,
        block(46, b"", 1),
        block(46, b"x", 2),
        block(49, b"", 2),
    ] {
        bad.extend(b"]U\x03\0x=yz");
        let p = parse(&doc(&file("19.10", &bad, &root())));
        assert_eq!(p.summary().domains[1].parsed_bytes, 0);
        assert_eq!(
            p.summary().diagnostics[0].code,
            "edrawings.user_data_profile_mismatch"
        );
    }
}
#[test]
fn profile_never_leaks_into_other_contexts_and_limits_remain_fatal() {
    let mut b = block(46, b"", 2);
    b.push(b'z');
    for (version, prefix) in [("19.10", vec![]), ("8.05", root()), ("18.00", root())] {
        let p = parse(&doc(&file(version, &b, &prefix)));
        assert!(p.summary().records.iter().all(|r| r.user_data.is_none()));
    }
    let raw = [b";; HSF V19.10 \n".as_slice(), &b].concat();
    assert_eq!(parse(&doc(&raw)).summary().records.len(), 0);
    let mut later = b"U\x03\0x=y".to_vec();
    later.extend(b.clone());
    assert_eq!(
        parse(&doc(&file("19.10", &later, &root())))
            .summary()
            .records
            .len(),
        4
    );
    let data = file("19.10", &b, &root());
    for limits in [
        Limits {
            max_hsf_string_bytes: 2,
            ..Default::default()
        },
        Limits {
            max_hsf_records: 3,
            ..Default::default()
        },
    ] {
        let d = read_bytes(
            &data,
            &ReadOptions {
                limits,
                ..Default::default()
            },
        )
        .unwrap();
        let e = d
            .parse_hsf_with_user_data(None, HsfMode::Partial, UserDataPolicy::EdrawingsFirstBeV2)
            .unwrap_err();
        let Error::Format(d) = e else {
            panic!("expected format diagnostic")
        };
        assert_eq!(d.classification, Status::LimitExceeded);
    }
}

#[test]
fn adjacent_handedness_authorizes_inventory_but_not_placements() {
    let header = block(46, b"", 2);
    let mut geometry = vec![b'l'];
    for f in [1f32, 2., 3., 4., 5., 6.] {
        geometry.extend(f.to_le_bytes());
    }
    for (anchor, allowed) in [
        (b"h\x00".as_slice(), true),
        (b"h\x01", true),
        (b"U\x03\0x=y", false),
        (b"h\x02", false),
    ] {
        let bytes = file(
            "19.10",
            &[header.as_slice(), anchor, &geometry, b"z"].concat(),
            &root(),
        );
        let s = doc(&bytes)
            .read_scene_with_user_data(None, HsfMode::Partial, UserDataPolicy::EdrawingsFirstBeV2)
            .unwrap();
        let summary = s.summary();
        assert_eq!(summary.status, Status::Partial);
        assert_eq!(summary.placement_status, Status::Unsupported);
        assert_eq!(summary.opaque_user_data.len(), usize::from(allowed));
        assert!(summary.instances.is_empty() && summary.primitive_instances.is_empty());
        if allowed {
            assert_eq!(summary.processed_records, summary.hsf.records.len() as u64);
            assert_eq!(summary.primitives.len(), 1);
            assert_eq!(
                s.primitive_points(&summary.primitives[0].id).unwrap(),
                &[[1., 2., 3.], [4., 5., 6.]]
            );
            assert_eq!(
                s.source_bytes(&summary.opaque_user_data[0].source).unwrap(),
                header
            );
        } else {
            assert_eq!(summary.processed_records, 3);
            assert!(summary.primitives.is_empty());
        }
    }
}

fn block_with_revision_string(revision: u32, text: &[u8]) -> Vec<u8> {
    fn blob(out: &mut Vec<u8>, b: &[u8]) {
        out.push(b.len() as u8);
        out.extend(b);
    }
    let mut p = vec![0xbe];
    for s in [
        b"2018-01.00".as_slice(),
        b"SWeModels-26.0.1.0001-2017284",
        b"",
        b"",
    ] {
        blob(&mut p, s);
    }
    p.push(0);
    p.extend([0; 64]);
    p.extend(revision.to_le_bytes());
    p.push(1);
    p.extend([0; 16]);
    blob(&mut p, b"");
    blob(&mut p, &[0; 16]);
    blob(&mut p, &[0; 16]);
    blob(&mut p, b"Config-12");
    p.extend([1, 0]);
    blob(&mut p, text);
    p.push(0);
    blob(&mut p, &[0; 24]);
    p.extend([0; 48]);
    let mut out = vec![b'['];
    out.extend((p.len() as u32 - 2).to_le_bytes());
    out.extend(p);
    out.push(b']');
    out
}
#[test]
fn revision_history_strings_must_end_with_the_current_revision() {
    for (text, ok) in [
        (b"51;".as_slice(), true),
        (b"<none>51;", true),
        (b"47;51;", true),
        (b"15;17;51;", true),
        (b"51;47;", false),
        (b"47;", false),
        (b"51", false),
        (b";51;", false),
        (b"<none>", false),
        (b"51;;", false),
    ] {
        let body = [block_with_revision_string(51, text), b"z".to_vec()].concat();
        let d = doc(&file("19.10", &body, &root()));
        let p = parse(&d);
        let s = p.summary();
        let accepted = s.records.len() > 3 && s.records[3].user_data.is_some();
        assert_eq!(accepted, ok, "{text:?}");
        if !ok {
            assert!(
                s.diagnostics
                    .iter()
                    .any(|d| d.code == "edrawings.user_data_profile_mismatch")
            );
        }
    }
}

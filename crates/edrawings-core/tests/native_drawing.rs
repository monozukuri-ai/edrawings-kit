use edrawings_core::*;

/// A fixed artifact saved/reopened by the official Reader. This offline test
/// checks the Rust parser, not another run of the native Viewer.
#[test]
fn corrected_native_drawing_retains_inventory_and_semantic_limits() {
    for (filename, record_count, japanese) in [
        ("two-layouts-visible-mm.edrw", 592, false),
        ("two-layouts-japanese-mm.edrw", 593, true),
    ] {
        let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
        // Maturin nests the Rust workspace one level deeper than the Python tests
        // in an sdist. Require the bundled fixture in either supported layout.
        let fixture = ["../../tests/fixtures", "../../../tests/fixtures"]
            .into_iter()
            .map(|base| manifest.join(base).join("native-m4").join(filename))
            .find(|path| path.is_file())
            .expect("bundled drawing fixture is missing");
        let input = std::fs::read(fixture).unwrap();
        let doc = read_bytes(&input, &ReadOptions::default()).unwrap();
        let result = doc
            .read_drawing_with_profiles(
                None,
                HsfMode::Partial,
                HsfProfiles {
                    user_data: UserDataPolicy::EdrawingsBeEnvelopeV1,
                    image: ImagePolicy::Edrawings1910U32V1,
                },
            )
            .unwrap();
        let s = result.summary();
        assert_eq!(s.scene.processed_records, record_count);
        assert!(s.scene.hsf.unparsed.is_empty());
        assert_eq!((s.scene.nodes.len(), s.scene.primitives.len()), (97, 74));
        assert_eq!(s.scene.placement_status, Status::Unsupported);
        assert!(s.scene.primitive_instances.is_empty());
        assert_eq!(s.assessment.dimension_status, Status::Unsupported);
        assert_eq!(s.assessment.sheet_status, Status::Unsupported);
        assert!(s.scene.nodes.iter().any(|n| {
            n.display.colors[2]
                .as_ref()
                .is_some_and(|color| color.value == [255, 0, 0])
        }));
        assert_eq!(
            s.scene
                .primitives
                .iter()
                .filter(|p| p.kind == "circle")
                .count(),
            3
        );
        let texts: Vec<_> = s
            .scene
            .primitives
            .iter()
            .filter_map(|p| p.text.as_ref())
            .collect();
        if japanese {
            assert_eq!(texts.len(), 1);
            let t = texts[0];
            assert_eq!(t.encoding, "utf_8");
            assert_eq!(t.encoding_code, Some(10));
            assert_eq!(t.value.as_deref(), Some("寸法確認 100 mm"));
            assert_eq!(t.status, Status::Complete);
            assert_eq!(
                result.scene().source_bytes(&t.source).unwrap(),
                "寸法確認 100 mm".as_bytes()
            );
        } else {
            assert!(texts.is_empty());
        }
        assert_eq!(s.sheet_inventory.status, Status::Complete);
        assert_eq!(s.sheet_inventory.sheets.len(), 3);
        assert_eq!(s.sheet_inventory.views.len(), 5);
        assert_eq!(
            s.sheet_inventory
                .sheets
                .iter()
                .map(|sheet| sheet.name.value.as_str())
                .collect::<Vec<_>>(),
            ["M4_SHEET_B", "M4_SHEET_A", "Model"]
        );
        assert_eq!(
            s.sheet_inventory
                .sheets
                .iter()
                .map(|sheet| sheet.primitive_ids.len())
                .sum::<usize>(),
            74
        );
        for sheet in &s.sheet_inventory.sheets {
            assert_eq!(
                result.scene().source_bytes(&sheet.name.source).unwrap(),
                sheet.name.value.as_bytes()
            );
        }
    }
}

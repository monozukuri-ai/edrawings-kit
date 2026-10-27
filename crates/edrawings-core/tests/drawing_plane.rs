use edrawings_core::*;

#[test]
fn native_drawing_xy_profile_is_source_backed_and_not_a_global_unit() {
    let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let fixture = ["../../tests/fixtures", "../../../tests/fixtures"]
        .into_iter()
        .map(|base| {
            manifest
                .join(base)
                .join("native-m4/two-layouts-visible-mm.edrw")
        })
        .find(|p| p.is_file())
        .expect("bundled native drawing fixture");
    let doc = read_bytes(&std::fs::read(fixture).unwrap(), &ReadOptions::default()).unwrap();
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
    let plane = s.drawing_plane_profile;
    assert_eq!(plane.status, Status::Complete);
    assert_eq!(
        plane.source_length_unit,
        Some(DrawingLengthUnit::Millimeter)
    );
    assert_eq!(plane.stored_xy_unit, Some(DrawingLengthUnit::Meter));
    assert_eq!(plane.xy_meters_per_saved_unit, Some(1.0));
    assert_eq!(plane.source_units_to_meters, Some(0.001));
    assert_eq!(plane.cad_origin, "unavailable");
    assert_eq!(plane.z_semantics, "uninterpreted_drawing_depth");
    let root = plane.root_length.as_ref().unwrap();
    let header = plane.header_unit.as_ref().unwrap();
    assert_eq!(result.scene().source_bytes(&root.source).unwrap(), b"3");
    assert_eq!(
        result.scene().source_bytes(&header.source).unwrap(),
        &[0, 0, 0, 0]
    );
    assert_eq!(s.scene.placement_status, Status::Unsupported);
    assert!(s.scene.units.is_none());
    assert!(s.scene.primitive_instances.is_empty());
    assert_eq!(s.assessment.dimension_status, Status::Unsupported);
    assert_eq!(s.assessment.status, Status::Partial);
}

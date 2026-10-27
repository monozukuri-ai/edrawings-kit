use edrawings_core::*;

#[test]
fn unicode_assignments_keep_wire_spans_and_do_not_establish_sheets() {
    let value = "NAME=`図面 🦀,A=B`,no hidden";
    let raw: Vec<u8> = value.encode_utf16().flat_map(u16::to_le_bytes).collect();
    let mut input = b";; HSF V19.10 \n\x16".to_vec();
    input.extend_from_slice(&(raw.len() as u16 / 2).to_le_bytes());
    input.extend_from_slice(&raw);
    input.push(0);
    let doc = read_bytes(&input, &ReadOptions::default()).unwrap();
    let drawing = doc.read_drawing(None, HsfMode::Partial).unwrap();
    let summary = drawing.summary();
    assert_eq!(summary.assessment.sheet_status, Status::Unsupported);
    assert_eq!(summary.user_option_records.len(), 1);
    let record = &summary.user_option_records[0];
    assert_eq!(record.parsing_status, Status::Complete);
    assert_eq!(record.assignments[0].name, "name");
    assert_eq!(record.assignments[0].value, "図面 🦀,A=B");
    let expected: Vec<u8> = "図面 🦀,A=B"
        .encode_utf16()
        .flat_map(u16::to_le_bytes)
        .collect();
    assert_eq!(
        drawing
            .scene()
            .source_bytes(record.assignments[0].value_source.as_ref().unwrap())
            .unwrap(),
        expected,
    );
    assert_eq!(record.assignments[1].value, "off");
    assert!(record.assignments[1].value_source.is_none());
    assert!(doc.read_drawing(None, HsfMode::Strict).is_err());
}

#[test]
fn malformed_later_assignment_does_not_publish_a_valid_prefix() {
    let value = b"name=Sheet1,refname=`broken";
    let mut input = b";; HSF V19.10 \nU".to_vec();
    input.extend_from_slice(&(value.len() as u16).to_le_bytes());
    input.extend_from_slice(value);
    input.push(0);
    let doc = read_bytes(&input, &ReadOptions::default()).unwrap();
    let drawing = doc.read_drawing(None, HsfMode::Partial).unwrap();
    let record = &drawing.summary().user_option_records[0];
    assert_eq!(record.parsing_status, Status::Unsupported);
    assert!(record.assignments.is_empty());
    assert_eq!(drawing.scene().source_bytes(&record.source).unwrap(), value);
}

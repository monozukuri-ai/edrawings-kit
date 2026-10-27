use crate::{Error, Extraction, Limits, Status, XmlMetadata, limits::bound};
use quick_xml::{Reader, XmlVersion, events::Event};

pub(crate) fn inspect_xml(extraction: &Extraction, limits: &Limits) -> Result<XmlMetadata, Error> {
    bound(
        extraction.data.len() as u64,
        limits.max_xml_bytes,
        "limits.xml_bytes",
    )?;
    // Validate UTF-8 XML only; preserve other encodings via extract().
    let xml = std::str::from_utf8(&extraction.data).map_err(|_| {
        Error::unsupported(
            "xml.encoding",
            "metadata",
            "Only UTF-8 XML validation is supported",
        )
    })?;
    let mut reader = Reader::from_reader(extraction.data.as_slice());
    reader.config_mut().enable_all_checks(true);
    let mut depth = 0u64;
    let mut max_depth = 0;
    let mut elements = 0;
    let mut roots = 0;
    let mut root_name = String::new();
    let bad = |message: &str| Error::invalid("xml.invalid", "metadata", message);
    loop {
        let event = reader.read_event().map_err(|e| bad(&e.to_string()))?;
        match &event {
            Event::Start(e) | Event::Empty(e) => {
                if depth == 0 {
                    roots += 1;
                    if roots > 1 {
                        return Err(bad("Multiple XML roots"));
                    }
                    root_name = std::str::from_utf8(e.name().as_ref())
                        .map_err(|_| bad("Invalid root name"))?
                        .into();
                }
                for attr in e.attributes() {
                    attr.map_err(|e| bad(&e.to_string()))?
                        .decoded_and_normalized_value(XmlVersion::Implicit1_0, reader.decoder())
                        .map_err(|e| bad(&e.to_string()))?;
                }
                elements += 1;
                bound(elements, limits.max_xml_elements, "limits.xml_elements")?;
                max_depth = max_depth.max(depth + 1);
                bound(max_depth, limits.max_xml_depth, "limits.xml_depth")?;
                if matches!(event, Event::Start(_)) {
                    depth += 1;
                }
            }
            Event::End(_) => {
                depth = depth
                    .checked_sub(1)
                    .ok_or_else(|| bad("Unmatched end tag"))?;
            }
            Event::DocType(_) => {
                return Err(Error::unsupported(
                    "xml.dtd",
                    "metadata",
                    "DTD declarations are not processed",
                ));
            }
            Event::Text(e) => {
                let text = e.decode().map_err(|e| bad(&e.to_string()))?;
                if depth == 0 && !text.trim().is_empty() {
                    return Err(bad("Text outside root"));
                }
            }
            Event::CData(_) if depth == 0 => return Err(bad("CDATA outside root")),
            Event::GeneralRef(e) => {
                if depth == 0 {
                    return Err(bad("Reference outside root"));
                }
                let name = e.decode().map_err(|e| bad(&e.to_string()))?;
                quick_xml::escape::unescape(&format!("&{name};"))
                    .map_err(|e| bad(&e.to_string()))?;
            }
            Event::Decl(e) => {
                if roots != 0 {
                    return Err(bad("XML declaration after root"));
                }
                if let Some(encoding) = e.encoding() {
                    let encoding = encoding.map_err(|e| bad(&e.to_string()))?;
                    if !encoding.eq_ignore_ascii_case(b"utf-8")
                        && !encoding.eq_ignore_ascii_case(b"us-ascii")
                    {
                        return Err(Error::unsupported(
                            "xml.encoding",
                            "metadata",
                            "Only UTF-8/ASCII XML declarations supported",
                        ));
                    }
                }
            }
            Event::Eof => break,
            _ => {}
        }
    }
    if depth != 0 || roots != 1 {
        return Err(bad("Missing root or incomplete XML element"));
    }
    // quick-xml preflights size/depth/entity restrictions without constructing
    // a tree. A conforming syntax check also rejects invalid names, characters,
    // declarations and attribute values that an event tokenizer can accept.
    // The tree is temporary and limited independently of text payload size.
    let options = roxmltree::ParsingOptions {
        allow_dtd: false,
        nodes_limit: limits
            .max_xml_elements
            .saturating_mul(4)
            .saturating_add(1)
            .min(u32::MAX as u64) as u32,
        ..Default::default()
    };
    roxmltree::Document::parse_with_options(xml, options).map_err(|e| {
        if matches!(e, roxmltree::Error::NodesLimitReached) {
            Error::limit("limits.xml_nodes", "XML node limit exceeded")
        } else {
            bad(&e.to_string())
        }
    })?;
    Ok(XmlMetadata {
        entry_id: extraction.info.entry_id.clone(),
        root_name,
        elements,
        max_depth,
        syntax_status: Status::Complete,
        semantic_status: Status::NotRequested,
        source: extraction.info.source.clone(),
    })
}

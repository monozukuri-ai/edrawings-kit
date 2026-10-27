use crate::*;
use crate::{container, hsf_adapter, limits::bound, metadata, probe, resources};
use serde::{Deserialize, Serialize};
use std::{io::Read, path::Path, sync::Arc};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct InspectOptions {
    pub limits: Limits,
    pub filename: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ReadOptions {
    pub limits: Limits,
    pub filename: Option<String>,
    pub read_metadata: bool,
    pub verify_all: bool,
}
impl Default for ReadOptions {
    fn default() -> Self {
        Self {
            limits: Limits::default(),
            filename: None,
            read_metadata: true,
            verify_all: false,
        }
    }
}

pub fn inspect_bytes(data: &[u8], options: &InspectOptions) -> Result<Inspection, Error> {
    let probe = probe_bytes(data, &options.limits)?;
    if let Some(d) = probe.diagnostics.first() {
        return Err(Error::Format(Box::new(d.clone())));
    }
    let mut result = Inspection {
        input_kind: probe.input_kind.clone(),
        document_kind: "unknown".into(),
        filename_hint: options.filename.clone(),
        file_bytes: data.len() as u64,
        file_sha256: sha256(data),
        prefix_bytes: 0,
        zip_offset_base: None,
        entries: vec![],
        hsf_candidates: vec![],
        header: probe.header,
        stages: Stages::default(),
        diagnostics: vec![],
    };
    match probe.input_kind {
        InputKind::RawHsf => {
            bound(1, options.limits.max_entries, "limits.entries")?;
            result.stages.hsf_header = Status::Complete;
            result.entries.push(EntryInfo {
                id: "raw:0".into(),
                ordinal: 0,
                name: "eModel".into(),
                raw_name: vec![],
                name_encoding: "synthetic".into(),
                role: "hsf".into(),
                compressed_bytes: data.len() as u64,
                bytes: data.len() as u64,
                compression_method: 0,
                flag_bits: 0,
                crc32: None,
                crc_status: "not_applicable".into(),
                header_range: ByteRange {
                    offset: 0,
                    length: result.header.as_ref().map_or(0, |h| h.byte_len),
                },
                data_range: ByteRange {
                    offset: 0,
                    length: data.len() as u64,
                },
                extraction_status: Status::NotRequested,
            });
        }
        InputKind::Zip | InputKind::PrefixedZip => {
            let prefix = if probe.input_kind == InputKind::PrefixedZip {
                probe::PREFIX_LEN
            } else {
                0
            };
            let idx = container::index(data, prefix, &options.limits)?;
            result.prefix_bytes = prefix as u64;
            result.zip_offset_base = Some(idx.offset_base);
            result.entries = idx.entries;
            result.diagnostics = idx.diagnostics;
        }
        InputKind::Unknown => {
            return Err(Error::unsupported(
                "container.unknown",
                "container",
                "Expected raw HSF, ZIP, or the observed eDrawings prefix",
            ));
        }
    }
    result.hsf_candidates = result
        .entries
        .iter()
        .filter(|e| e.role == "hsf")
        .map(|e| e.id.clone())
        .collect();
    result
        .diagnostics
        .extend(probe::candidate_diagnostics(&result.hsf_candidates));
    Ok(result)
}

pub(crate) fn load_path(path: &Path, limits: &Limits) -> Result<Vec<u8>, Error> {
    let file = std::fs::File::open(path)?;
    bound(
        file.metadata()?.len(),
        limits.max_file_bytes,
        "limits.file_bytes",
    )?;
    let mut data = Vec::new();
    // A growing file cannot bypass the metadata check.
    file.take(limits.max_file_bytes.saturating_add(1))
        .read_to_end(&mut data)?;
    bound(
        data.len() as u64,
        limits.max_file_bytes,
        "limits.file_bytes",
    )?;
    Ok(data)
}
pub fn inspect_path(path: impl AsRef<Path>, options: &InspectOptions) -> Result<Inspection, Error> {
    inspect_bytes(&load_path(path.as_ref(), &options.limits)?, options)
}
pub fn probe_path(path: impl AsRef<Path>, limits: &Limits) -> Result<ProbeResult, Error> {
    let mut file = std::fs::File::open(path)?;
    bound(
        file.metadata()?.len(),
        limits.max_file_bytes,
        "limits.file_bytes",
    )?;
    let mut data = [0; 96];
    let mut used = 0;
    while used < data.len() {
        let n = file.read(&mut data[used..])?;
        if n == 0 {
            break;
        }
        used += n;
    }
    probe_bytes(&data[..used], limits)
}

#[derive(Clone, Debug)]
pub struct Document {
    original: Arc<[u8]>,
    limits: Limits,
    inspection: Inspection,
    metadata: Vec<XmlMetadata>,
}
pub fn read_bytes(data: &[u8], options: &ReadOptions) -> Result<Document, Error> {
    bound(
        data.len() as u64,
        options.limits.max_file_bytes,
        "limits.file_bytes",
    )?;
    bound(
        data.len() as u64,
        options.limits.max_output_bytes,
        "limits.output_bytes",
    )?;
    from_owned(Arc::from(data), options)
}
pub fn read_path(path: impl AsRef<Path>, options: &ReadOptions) -> Result<Document, Error> {
    let data = load_path(path.as_ref(), &options.limits)?;
    bound(
        data.len() as u64,
        options.limits.max_output_bytes,
        "limits.output_bytes",
    )?;
    from_owned(Arc::from(data), options)
}
fn from_owned(data: Arc<[u8]>, options: &ReadOptions) -> Result<Document, Error> {
    let inspection = inspect_bytes(
        &data,
        &InspectOptions {
            limits: options.limits.clone(),
            filename: options.filename.clone(),
        },
    )?;
    let mut doc = Document {
        original: data,
        limits: options.limits.clone(),
        inspection,
        metadata: vec![],
    };
    let mut budget = doc.operation_budget()?;
    for i in 0..doc.inspection.entries.len() {
        let entry = &doc.inspection.entries[i];
        let is_xml = options.read_metadata && entry.role == "metadata";
        if !is_xml && !options.verify_all {
            continue;
        }
        if is_xml {
            bound(entry.bytes, doc.limits.max_xml_bytes, "limits.xml_bytes")?;
        }
        let extraction = doc.extract_budget(&entry.id, &mut budget)?;
        if is_xml {
            let metadata = metadata::inspect_xml(&extraction, &doc.limits).map_err(|e| {
                if let Error::Format(mut d) = e {
                    d.entry_id = Some(extraction.info.entry_id.clone());
                    d.domain_id = Some(extraction.info.source.domain_id.clone());
                    Error::Format(d)
                } else {
                    e
                }
            })?;
            doc.metadata.push(metadata);
        }
        doc.inspection.entries[i].crc_status = extraction.info.crc_status;
        doc.inspection.entries[i].extraction_status = Status::Complete;
    }
    if options.read_metadata {
        // This stage is explicitly structural XML inspection, not product semantics.
        doc.inspection.stages.metadata = if doc.metadata.is_empty() {
            Status::Complete
        } else {
            Status::Partial
        };
        if !doc.metadata.is_empty() {
            let mut d = Diagnostic::new(
                "metadata.semantics_not_parsed",
                Status::Partial,
                "metadata",
                "XML structure inspected; product-specific semantics are not parsed",
            );
            d.severity = "info".into();
            doc.inspection.diagnostics.push(d);
        }
    }
    Ok(doc)
}
impl Document {
    pub fn inspection(&self) -> &Inspection {
        &self.inspection
    }
    pub fn metadata(&self) -> &[XmlMetadata] {
        &self.metadata
    }
    fn operation_budget(&self) -> Result<hsf_core::Budget, Error> {
        let mut budget = self.limits.budget();
        budget.charge_input(self.original.len() as u64)?;
        budget.charge_output(self.original.len() as u64)?;
        Ok(budget)
    }
    fn extract_budget(&self, id: &str, budget: &mut hsf_core::Budget) -> Result<Extraction, Error> {
        let entry = self
            .inspection
            .entries
            .iter()
            .find(|e| e.id == id)
            .ok_or_else(|| Error::invalid("entry.not_found", "extraction", "Unknown entry ID"))?;
        resources::extract(
            &self.original,
            entry,
            &self.inspection.file_sha256,
            &self.limits,
            budget,
        )
        .map_err(|e| {
            if let Error::Format(mut d) = e {
                d.entry_id = Some(id.into());
                Error::Format(d)
            } else {
                e
            }
        })
    }
    pub fn extract(&self, entry_id: &str) -> Result<Extraction, Error> {
        self.extract_budget(entry_id, &mut self.operation_budget()?)
    }
    /// Verifies all entries under one cumulative budget. No decoded payload cache.
    pub fn verify_all(&self) -> Result<Vec<ExtractionInfo>, Error> {
        let mut budget = self.operation_budget()?;
        self.inspection
            .entries
            .iter()
            .map(|e| self.extract_budget(&e.id, &mut budget).map(|x| x.info))
            .collect()
    }
    /// H0 only: extract/CRC-check a selected HSF and parse its identification line.
    pub fn inspect_hsf(&self, entry_id: Option<&str>) -> Result<HsfInspection, Error> {
        let id = self.hsf_entry(entry_id)?;
        self.inspect_hsf_entry(id)
    }
    fn hsf_entry<'a>(&'a self, entry_id: Option<&'a str>) -> Result<&'a str, Error> {
        Ok(match entry_id {
            Some(id) => id,
            None => match self.inspection.hsf_candidates.as_slice() {
                [id] => id,
                [] => {
                    return Err(Error::unsupported(
                        "hsf.no_candidate",
                        "hsf_header",
                        "No eModel/raw HSF candidate",
                    ));
                }
                _ => {
                    return Err(Error::unsupported(
                        "hsf.ambiguous_candidates",
                        "hsf_header",
                        "Specify an entry ID",
                    ));
                }
            },
        })
    }
    /// Parse supported HSF syntax. Strict rejects unsupported syntax; partial
    /// returns only the valid prefix. Invalid input and exhausted budgets error.
    pub fn parse_hsf(&self, entry_id: Option<&str>, mode: HsfMode) -> Result<HsfDocument, Error> {
        self.parse_hsf_with_user_data(entry_id, mode, UserDataPolicy::Disabled)
    }
    pub fn parse_hsf_with_user_data(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        user_data: UserDataPolicy,
    ) -> Result<HsfDocument, Error> {
        self.parse_hsf_with_profiles(
            entry_id,
            mode,
            HsfProfiles {
                user_data,
                ..Default::default()
            },
        )
    }
    pub fn parse_hsf_with_profiles(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        profiles: HsfProfiles,
    ) -> Result<HsfDocument, Error> {
        let id = self.hsf_entry(entry_id)?;
        let mut budget = self.operation_budget()?;
        let extraction = self.extract_budget(id, &mut budget)?;
        hsf_adapter::parse(
            extraction,
            mode,
            profiles,
            &self.limits,
            self.inspection.stages.clone(),
            &mut budget,
        )
    }
    /// Decode the supported generic 3D scene using one cumulative operation budget.
    pub fn read_scene(&self, entry_id: Option<&str>, mode: HsfMode) -> Result<SceneResult, Error> {
        self.read_scene_with_user_data(entry_id, mode, UserDataPolicy::Disabled)
    }
    pub fn read_scene_with_user_data(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        user_data: UserDataPolicy,
    ) -> Result<SceneResult, Error> {
        self.read_scene_with_profiles(
            entry_id,
            mode,
            HsfProfiles {
                user_data,
                ..Default::default()
            },
        )
    }
    pub fn read_scene_with_profiles(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        profiles: HsfProfiles,
    ) -> Result<SceneResult, Error> {
        self.read_scene_with_context(entry_id, mode, profiles, &SceneContext::default())
    }
    /// Use an explicit import root for inventory; external state and placements remain unsupported.
    pub fn read_scene_with_context(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        profiles: HsfProfiles,
        context: &SceneContext,
    ) -> Result<SceneResult, Error> {
        let id = self.hsf_entry(entry_id)?;
        let mut budget = self.operation_budget()?;
        let extraction = self.extract_budget(id, &mut budget)?;
        crate::scene_adapter::read(
            extraction,
            mode,
            profiles,
            context,
            &self.limits,
            self.inspection.stages.clone(),
            &mut budget,
        )
    }
    /// Inspect drawing primitives. Strict also requires verified document semantics,
    /// which are not yet available in this experimental profile.
    pub fn read_drawing(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
    ) -> Result<DrawingResult, Error> {
        self.read_drawing_with_user_data(entry_id, mode, UserDataPolicy::Disabled)
    }
    pub fn read_drawing_with_user_data(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        user_data: UserDataPolicy,
    ) -> Result<DrawingResult, Error> {
        self.read_drawing_with_profiles(
            entry_id,
            mode,
            HsfProfiles {
                user_data,
                ..Default::default()
            },
        )
    }
    pub fn read_drawing_with_profiles(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        profiles: HsfProfiles,
    ) -> Result<DrawingResult, Error> {
        self.read_drawing_with_context(entry_id, mode, profiles, &SceneContext::default())
    }
    /// Use an explicit import root for inventory; external state and placements remain unsupported.
    pub fn read_drawing_with_context(
        &self,
        entry_id: Option<&str>,
        mode: HsfMode,
        profiles: HsfProfiles,
        context: &SceneContext,
    ) -> Result<DrawingResult, Error> {
        let id = self.hsf_entry(entry_id)?;
        let mut budget = self.operation_budget()?;
        let extraction = self.extract_budget(id, &mut budget)?;
        // Assessment metadata shares the extraction/syntax/scene budget.
        budget.charge_output(2048)?;
        let scene = crate::scene_adapter::read(
            extraction,
            mode,
            profiles,
            context,
            &self.limits,
            self.inspection.stages.clone(),
            &mut budget,
        )?;
        DrawingResult::new(scene, mode, &mut budget)
    }
    fn inspect_hsf_entry(&self, id: &str) -> Result<HsfInspection, Error> {
        let extraction = self.extract(id)?;
        let header = hsf_adapter::header(&extraction.data).map_err(|e| {
            if let Error::Format(mut d) = e {
                d.entry_id = Some(id.into());
                d.domain_id = Some(extraction.info.source.domain_id.clone());
                d.byte_range = Some(ByteRange {
                    offset: 0,
                    length: extraction.data.len().min(hsf_core::MAX_HEADER_BYTES) as u64,
                });
                Error::Format(d)
            } else {
                e
            }
        })?;
        let unparsed_range = ByteRange {
            offset: header.byte_len,
            length: extraction.info.bytes - header.byte_len,
        };
        Ok(HsfInspection {
            entry_id: id.into(),
            header,
            header_status: Status::Complete,
            syntax_status: Status::NotRequested,
            unparsed_range,
            source: extraction.info.source,
            diagnostics: vec![],
        })
    }
}

//! Opt-in empirical profiles of eDrawings 0xBE headers and terminal envelopes.
//! Field walking establishes the boundary; the declared size only corroborates
//! it. The constant one-byte deficit's origin and all product semantics are unknown.
use hsf_core::{
    HsfError, SourceSpan, Status, UserDataContext, UserDataField, UserDataLayout, UserDataProfile,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UserDataPolicy {
    #[default]
    Disabled,
    EdrawingsFirstBeV2,
    /// FirstBeV2 plus closed terminal envelopes. No product field semantics.
    EdrawingsBeEnvelopeV1,
}
pub(crate) struct FirstBe;
pub(crate) static FIRST_BE: FirstBe = FirstBe;
struct BeEnvelope;
static BE_ENVELOPE: BeEnvelope = BeEnvelope;
impl UserDataPolicy {
    pub(crate) fn profile(self) -> Option<&'static dyn UserDataProfile> {
        match self {
            Self::Disabled => None,
            Self::EdrawingsFirstBeV2 => Some(&FIRST_BE),
            Self::EdrawingsBeEnvelopeV1 => Some(&BE_ENVELOPE),
        }
    }
    /// Inventory authorization is narrower than syntax opt-in: the empirical
    /// root header must be followed immediately by a fully framed h or }.
    /// This does not authorize placements or interpretation of private fields.
    pub(crate) fn inventory_record(self, parsed: &hsf_core::HsfDocument) -> Option<String> {
        if matches!(self, Self::Disabled) {
            return None;
        }
        let r = parsed.records.get(3)?;
        let next = parsed.records.get(4)?;
        if r.opcode != b'['
            || r.user_data.is_none()
            || r.scope.is_some()
            || r.source.domain_id != "hsf:1"
            || r.source.offset != 0
            || parsed.records[..3]
                .iter()
                .map(|r| r.opcode)
                .ne([b'I', b'B', b'Z'])
            || next.source.domain_id != r.source.domain_id
            || r.source.offset.checked_add(r.source.length) != Some(next.source.offset)
            || !matches!(next.opcode, b'h' | b'}')
        {
            return None;
        }
        Some(r.id.clone())
    }

    /// Only authorize a fully framed, final compressed record. The backend
    /// separately checks the terminal record arrangement before scene inventory.
    pub(crate) fn inventory_terminal_record(
        self,
        parsed: &hsf_core::HsfDocument,
    ) -> Option<String> {
        if !matches!(self, Self::EdrawingsBeEnvelopeV1) || self.inventory_record(parsed).is_none() {
            return None;
        }
        let tail = parsed.records.get(parsed.records.len().checked_sub(3)?..)?;
        let [r, stop, end] = tail else {
            return None;
        };
        let layout = r.user_data.as_ref()?;
        if r.opcode != b'['
            || r.scope.is_some()
            || !layout.profile.starts_with("edrawings-terminal-be-v1-")
            || stop.opcode != b'z'
            || end.opcode != 0
            || r.source.domain_id != "hsf:1"
            || end.source.domain_id != "hsf:0"
            || parsed.domains.iter().any(|d| d.parsed_bytes != d.byte_len)
        {
            return None;
        }
        Some(r.id.clone())
    }
}
fn mismatch(message: &str) -> HsfError {
    HsfError {
        diagnostic: Box::new(hsf_core::Diagnostic {
            code: "edrawings.user_data_profile_mismatch".into(),
            severity: "warning".into(),
            classification: Status::Unsupported,
            stage: "hsf_syntax".into(),
            source: None,
            opcode: Some(b'['),
            version: None,
            impact: None,
            message: message.into(),
        }),
    }
}
struct Cursor<'a> {
    bytes: &'a [u8],
    domain: &'a str,
    at: usize,
    base_offset: u64,
    max_string: u64,
    fields: Vec<UserDataField>,
}
impl<'a> Cursor<'a> {
    fn take(&mut self, label: &str, n: usize) -> Result<&'a [u8], HsfError> {
        let end = self
            .at
            .checked_add(n)
            .ok_or_else(|| mismatch("Field range overflow"))?;
        let bytes = self
            .bytes
            .get(self.at..end)
            .ok_or_else(|| mismatch("Truncated or oversized empirical header"))?;
        self.fields.push(UserDataField {
            label: label.into(),
            source: SourceSpan {
                domain_id: self.domain.into(),
                offset: self
                    .base_offset
                    .checked_add(self.at as u64)
                    .ok_or_else(|| mismatch("Field offset overflow"))?,
                length: n as u64,
            },
        });
        self.at = end;
        Ok(bytes)
    }
    fn byte(&mut self, label: &str) -> Result<u8, HsfError> {
        Ok(self.take(label, 1)?[0])
    }
    fn word(&mut self, label: &str) -> Result<u32, HsfError> {
        Ok(u32::from_le_bytes(
            self.take(label, 4)?.try_into().expect("four"),
        ))
    }
    fn blob(&mut self, label: &str, expected: Option<u8>) -> Result<&'a [u8], HsfError> {
        let n = self.byte(&format!("{label}_length"))?;
        if expected.is_some_and(|value| value != n) {
            return Err(mismatch("Opaque blob size is outside the observed profile"));
        }
        if u64::from(n) > self.max_string {
            let mut e = mismatch("User Data field exceeds max_hsf_string_bytes");
            e.diagnostic.code = "hsf.limit_string".into();
            e.diagnostic.classification = Status::LimitExceeded;
            return Err(e);
        }
        self.take(label, usize::from(n))
    }
    fn flag(&mut self, label: &str) -> Result<(), HsfError> {
        if self.byte(label)? > 1 {
            return Err(mismatch("Flag is outside the observed profile"));
        }
        Ok(())
    }
}
fn finite(bytes: &[u8]) -> Result<(), HsfError> {
    if bytes
        .chunks_exact(4)
        .any(|b| !f32::from_le_bytes(b.try_into().expect("four")).is_finite())
    {
        return Err(mismatch("Nonfinite float candidate"));
    }
    Ok(())
}
impl UserDataProfile for FirstBe {
    fn frame(
        &self,
        context: UserDataContext<'_>,
        bytes: &[u8],
    ) -> Result<Option<UserDataLayout>, HsfError> {
        // Narrow context matters as much as payload shape. No later blocks, raw
        // domain records, alternate root prefixes, or additional decoded domains.
        let root = context.preceding_records;
        if context.domain_id != "hsf:1"
            || context.offset != 0
            || !context.compressed
            || root.len() != 3
            || root.iter().map(|r| r.opcode).ne([b'I', b'B', b'Z'])
            || root
                .iter()
                .any(|r| r.source.domain_id != "hsf:0" || r.scope.is_some())
            || root[0].source.offset != context.header.byte_len
            || bytes.get(5) != Some(&0xBE)
        {
            return Ok(None);
        }
        let mut c = Cursor {
            bytes,
            domain: context.domain_id,
            at: 0,
            base_offset: context.offset,
            max_string: context.max_string_bytes,
            fields: Vec::with_capacity(35),
        };
        if c.byte("start")? != b'[' {
            return Ok(None);
        }
        let declared = c.word("declared_length")?;
        if declared > 4090 {
            return Err(mismatch("Declared length exceeds empirical profile bound"));
        }
        c.byte("private_identifier")?;
        for i in 0..4 {
            c.blob(&format!("leading_string_{i}"), None)?;
        }
        c.flag("flag_0")?;
        finite(c.take("matrix_candidate", 64)?)?;
        let revision = c.word("internal_revision")?;
        let tail = match (
            context.header.version.major,
            context.header.version.minor,
            revision,
        ) {
            (8, 5, 22) => 4,
            (14, 50, 39) | (19, 10, 45 | 46 | 47 | 48 | 51) => 48,
            _ => return Err(mismatch("Unverified HSF/revision pair")),
        };
        c.flag("flag_1")?;
        c.take("opaque_words", 16)?;
        let include_len = c.blob("include_path_candidate", None)?.len();
        c.blob("opaque_blob_0", Some(16))?;
        c.blob("opaque_blob_1", Some(16))?;
        c.blob("configuration_candidate", None)?;
        c.take("opaque_flags", 2)?;
        let text = c.blob("revision_string_candidate", None)?;
        if text != format!("{revision};").as_bytes()
            && text != format!("<none>{revision};").as_bytes()
        {
            return Err(mismatch("Revision integer and string disagree"));
        }
        c.take("opaque_flag", 1)?;
        c.blob("opaque_blob_2", Some(24))?;
        let tail_bytes = c.take("revision_tail", tail)?;
        if tail == 48 {
            finite(&tail_bytes[12..44])?;
        }
        let payload = (c.at - 5) as u32;
        // Do not use this relation to seek. Check it only AFTER the field walk.
        if payload.checked_sub(declared) != Some(1 + u32::from(include_len == 0)) {
            return Err(mismatch(
                "Field boundary disagrees with conditional length accounting",
            ));
        }
        if c.byte("stop")? != b']' {
            return Err(mismatch("Missing stop at computed boundary"));
        }
        Ok(Some(UserDataLayout {
            profile: format!(
                "edrawings-first-be-v2-hsf-{}-revision-{revision}",
                context.header.version.text
            ),
            declared_length: declared,
            computed_payload_length: payload,
            fields: c.fields,
        }))
    }
}

impl UserDataProfile for BeEnvelope {
    fn max_framing_bytes(&self) -> usize {
        // The revision-47 bitmap tail is larger than the 4 KiB header profile.
        // This is a borrowed view of already budgeted input, never a new buffer.
        1 << 20
    }
    fn frame(
        &self,
        context: UserDataContext<'_>,
        bytes: &[u8],
    ) -> Result<Option<UserDataLayout>, HsfError> {
        if context.offset == 0 {
            return FIRST_BE.frame(context, bytes);
        }
        let root = context.preceding_records;
        let Some(first) = root.get(3) else {
            return Ok(None);
        };
        let Some(first_layout) = first.user_data.as_ref() else {
            return Ok(None);
        };
        let Some(last) = root.last() else {
            return Ok(None);
        };
        if context.domain_id != "hsf:1"
            || !context.compressed
            || context.segment_depth != 0
            || context.parent_suffix != Some(b"\0".as_slice())
            || context.offset.checked_add(bytes.len() as u64) != Some(context.domain_byte_len)
            || first.source.domain_id != context.domain_id
            || first.source.offset != 0
            || first.opcode != b'['
            || first.scope.is_some()
            || last.opcode != 1
            || last.scope.is_some()
            || last.source.domain_id != context.domain_id
            || last.source.offset.checked_add(last.source.length) != Some(context.offset)
            || root.iter().filter(|r| r.opcode == b'[').count() != 1
        {
            return Ok(None);
        }
        let candidates: &[u32] = match (context.header.version.major, context.header.version.minor)
        {
            (8, 5) => &[22],
            (14, 50) => &[39],
            (19, 10) => &[45, 46, 47, 48, 51],
            _ => return Ok(None),
        };
        let Some(&revision) = candidates.iter().find(|revision| {
            first_layout.profile
                == format!(
                    "edrawings-first-be-v2-hsf-{}-revision-{revision}",
                    context.header.version.text
                )
        }) else {
            return Ok(None);
        };
        if revision == 47 {
            return terminal_bitmaps(context, bytes, revision).map(Some);
        }
        // This is an exact opaque envelope, not a guess about integer widths or
        // a correction added to the declared length. It must occupy the entire
        // remaining decoded domain, followed by z, and the parent must end in 0.
        let zeros = if revision == 22 { 8 } else { 12 };
        if bytes.len() != 12 + zeros || bytes.last() != Some(&b'z') {
            return Err(mismatch(
                "Terminal envelope does not fill the remaining compressed domain",
            ));
        }
        let mut c = Cursor {
            bytes,
            domain: context.domain_id,
            at: 0,
            base_offset: context.offset,
            max_string: context.max_string_bytes,
            fields: Vec::with_capacity(6),
        };
        if c.byte("start")? != b'['
            || c.word("declared_length")? != 9
            || c.byte("private_identifier")? != 0xbe
            || c.word("internal_revision")? != revision
            || c.take("opaque_zero_tail", zeros)?.iter().any(|&b| b != 0)
        {
            return Err(mismatch(
                "Terminal envelope bytes or revision differ from the observed profile",
            ));
        }
        let payload = (c.at - 5) as u32;
        if c.byte("stop")? != b']' {
            return Err(mismatch("Terminal envelope stop is missing"));
        }
        Ok(Some(UserDataLayout {
            profile: format!(
                "edrawings-terminal-be-v1-hsf-{}-revision-{revision}",
                context.header.version.text
            ),
            declared_length: 9,
            computed_payload_length: payload,
            fields: c.fields,
        }))
    }
}

/// Observed revision-47 terminal envelope with embedded uncompressed bitmap
/// payloads. The 96-byte carrier is opaque except for a corroborating DIB header.
/// Its image ordering is not asserted to be configuration ordering.
fn terminal_bitmaps(
    context: UserDataContext<'_>,
    bytes: &[u8],
    revision: u32,
) -> Result<UserDataLayout, HsfError> {
    // The backend reserves 64 metadata fields before invoking this callback.
    // Four fields per bitmap plus eight envelope fields fit at most 14 images.
    const MAX_BITMAPS: u32 = 14;
    let mut c = Cursor {
        bytes,
        domain: context.domain_id,
        at: 0,
        base_offset: context.offset,
        max_string: context.max_string_bytes,
        fields: Vec::with_capacity(64),
    };
    if c.byte("start")? != b'['
        || c.word("declared_length")? != 9
        || c.byte("private_identifier")? != 0xbe
        || c.word("internal_revision")? != revision
        || c.word("opaque_reserved")? != 0
    {
        return Err(mismatch(
            "Terminal bitmap envelope header differs from the observed profile",
        ));
    }
    let count = c.word("bitmap_count")?;
    if !(1..=MAX_BITMAPS).contains(&count) {
        return Err(mismatch(
            "Terminal bitmap count is outside the bounded 1..14 profile",
        ));
    }
    for index in 0..count {
        if c.word(&format!("bitmap_{index}_carrier_length"))? != 96 {
            return Err(mismatch("Unknown terminal bitmap carrier layout"));
        }
        let carrier = c.take(&format!("bitmap_{index}_carrier"), 96)?;
        let u32_at = |at| u32::from_le_bytes(carrier[at..at + 4].try_into().unwrap());
        let u16_at = |at| u16::from_le_bytes(carrier[at..at + 2].try_into().unwrap());
        let width = u32_at(36) as i32;
        let height = u32_at(40) as i32;
        if u32_at(32) != 40
            || !(1..=4096).contains(&width)
            || height == 0
            || height.unsigned_abs() > 4096
            || u16_at(44) != 1
            || u16_at(46) != 24
            || u32_at(48) != 0
            || u32_at(64) != 0
        {
            return Err(mismatch("Unsupported terminal bitmap DIB profile"));
        }
        let stride = (width as u32 * 24).div_ceil(32) * 4;
        let expected = stride * height.unsigned_abs();
        let length = c.word(&format!("bitmap_{index}_pixels_length"))?;
        if length != expected || u32_at(52) != expected {
            return Err(mismatch(
                "Terminal bitmap length disagrees with dimensions and stride",
            ));
        }
        c.take(&format!("bitmap_{index}_pixels"), length as usize)?;
    }
    if c.word("opaque_trailing_zero")? != 0 {
        return Err(mismatch("Unknown terminal bitmap suffix"));
    }
    let payload = (c.at - 5) as u32;
    if c.byte("stop")? != b']' || bytes.get(c.at..) != Some(b"z".as_slice()) {
        return Err(mismatch(
            "Terminal bitmaps do not fill the remaining compressed domain",
        ));
    }
    Ok(UserDataLayout {
        profile: format!(
            "edrawings-terminal-be-v1-hsf-{}-revision-{revision}-bitmaps-v1",
            context.header.version.text
        ),
        declared_length: 9,
        computed_payload_length: payload,
        fields: c.fields,
    })
}

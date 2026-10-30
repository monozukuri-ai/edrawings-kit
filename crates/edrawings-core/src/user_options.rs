//! Stored HC_Set_User_Options assignments. Product keys and effective attribute
//! inheritance are deliberately separate from this bounded grammar parser.
use crate::*;

const MAX_ASSIGNMENTS: u64 = 4096;

#[derive(Clone, Copy)]
struct Position {
    text: usize,
    wire: u64,
}

struct Cursor<'a> {
    text: &'a str,
    encoding: &'a str,
    base: &'a HsfSpan,
    at: Position,
}
impl Cursor<'_> {
    fn peek(&self) -> Option<char> {
        self.text[self.at.text..].chars().next()
    }
    fn next(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.at.text += c.len_utf8();
        self.at.wire += match self.encoding {
            "utf_16_le" => c.len_utf16() as u64 * 2,
            "utf_32_le" => 4,
            _ => 1,
        };
        Some(c)
    }
    fn whitespace(&mut self) {
        while self.peek().is_some_and(|c| c.is_ascii_whitespace()) {
            self.next();
        }
    }
    fn span(&self, start: Position, end: Position) -> HsfSpan {
        HsfSpan {
            domain_id: self.base.domain_id.clone(),
            offset: self.base.offset + start.wire,
            length: end.wire - start.wire,
        }
    }
    fn slice(&self, start: Position, end: Position) -> &str {
        &self.text[start.text..end.text]
    }
}

// ASCII names are a bounded subset. Do not guess locale-sensitive folding of
// non-ASCII option names or interpret punctuation as additional grammar.
fn supported_name(name: &str) -> bool {
    name.as_bytes()
        .first()
        .is_some_and(|b| b.is_ascii_alphabetic() || *b == b'_')
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b" _-.".contains(&b))
}

fn assignments(
    text: &TextValue,
    budget: &mut hsf_core::Budget,
) -> Result<Result<Vec<UserOptionAssignment>, &'static str>, Error> {
    let Some(value) = text.value.as_deref() else {
        return Ok(Err("drawing.user_options_encoding"));
    };
    if !matches!(
        text.encoding.as_str(),
        "ascii" | "iso_8859_1" | "utf_16_le" | "utf_32_le"
    ) {
        return Ok(Err("drawing.user_options_encoding"));
    }
    let unsupported = || Ok(Err("drawing.user_options_syntax"));
    if value
        .chars()
        .any(|c| c.is_control() && !c.is_ascii_whitespace())
    {
        return unsupported();
    }
    let mut c = Cursor {
        text: value,
        encoding: &text.encoding,
        base: &text.source,
        at: Position { text: 0, wire: 0 },
    };
    let mut result = Vec::new();
    c.whitespace();
    while c.peek().is_some() {
        crate::limits::bound(
            result.len() as u64 + 1,
            MAX_ASSIGNMENTS,
            "limits.drawing_user_options",
        )?;
        // Strings, Vec growth, and up to four independently owned source spans.
        budget.charge_output(1024 + 4 * text.source.domain_id.len() as u64)?;
        let start = c.at;
        let mut name_start = start;
        let mut name_end = start;
        while let Some(ch) = c.peek() {
            if ch == '=' || ch == ',' {
                break;
            }
            c.next();
            if !ch.is_ascii_whitespace() {
                name_end = c.at;
            }
        }
        let explicit = c.peek() == Some('=');
        let name = c.slice(name_start, name_end);
        if !explicit && name.eq_ignore_ascii_case("no") {
            return unsupported();
        }
        let mut implicit_off = false;
        if !explicit && name.get(..3).is_some_and(|s| s.eq_ignore_ascii_case("no ")) {
            name_start.text += 3;
            name_start.wire += if text.encoding == "utf_16_le" {
                6
            } else if text.encoding == "utf_32_le" {
                12
            } else {
                3
            };
            // A single space after 'no' is the supported shorthand spelling.
            implicit_off = true;
        }
        let name = c.slice(name_start, name_end);
        if !supported_name(name) || name.starts_with(' ') {
            return Ok(Err("drawing.user_options_name"));
        }
        let name = name.to_ascii_lowercase();
        let name_source = c.span(name_start, name_end);
        let (value, value_kind, value_source, token_source, end) = if explicit {
            c.next();
            c.whitespace();
            let token_start = c.at;
            let mut value_start = c.at;
            let mut value_end = c.at;
            let token_end;
            if let Some(quote @ ('\'' | '"' | '`')) = c.peek() {
                c.next();
                value_start = c.at;
                while let Some(ch) = c.peek() {
                    if ch == quote {
                        break;
                    }
                    c.next();
                }
                value_end = c.at;
                if c.next() != Some(quote) {
                    return unsupported();
                }
                token_end = c.at;
                c.whitespace();
                if c.peek().is_some_and(|ch| ch != ',') {
                    return unsupported();
                }
            } else {
                while let Some(ch) = c.peek() {
                    if ch == ',' {
                        break;
                    }
                    // Quotes and embedded '=' require quoting. There is no
                    // inferred escaping or numeric/list grammar inside values.
                    if matches!(ch, '=' | '\'' | '"' | '`') {
                        return unsupported();
                    }
                    c.next();
                    if !ch.is_ascii_whitespace() {
                        value_end = c.at;
                    }
                }
                token_end = value_end;
            }
            (
                c.slice(value_start, value_end).to_string(),
                "explicit",
                Some(c.span(value_start, value_end)),
                Some(c.span(token_start, token_end)),
                token_end,
            )
        } else {
            (
                if implicit_off { "off" } else { "on" }.into(),
                if implicit_off {
                    "implicit_off"
                } else {
                    "implicit_on"
                },
                None,
                None,
                name_end,
            )
        };
        result.push(UserOptionAssignment {
            name,
            value,
            value_kind: value_kind.into(),
            source: c.span(start, end),
            name_source,
            value_source,
            value_token_source: token_source,
        });
        if c.peek() == Some(',') {
            c.next();
            c.whitespace();
            if c.peek().is_none() {
                return unsupported();
            }
        }
    }
    // Wire accounting is independent of UTF-8 string indices.
    if c.at.wire != text.source.length {
        return Ok(Err("drawing.user_options_encoding"));
    }
    Ok(Ok(result))
}

/// eDrawings 2026 (HOOPS Exchange imports) writes Unicode Options by widening
/// the UTF-8 bytes of a name with sign extension: every byte above 0x7f becomes
/// the code unit 0xff00 | byte (`ピン` arrives as U+FFE3 U+FF83 U+FF94 …).
/// Genuine text never consists solely of ASCII and U+FF80–U+FFFF code units
/// that also form valid multi-byte UTF-8, so the intended text is recovered
/// exactly; anything else is left untouched.
fn sign_extended_utf8(value: &str) -> Option<String> {
    let mut widened = false;
    let mut bytes = Vec::with_capacity(value.len());
    for c in value.chars() {
        let code = u32::from(c);
        if code < 0x80 {
            bytes.push(code as u8);
        } else if (0xff80..=0xffff).contains(&code) {
            widened = true;
            bytes.push((code & 0xff) as u8);
        } else {
            return None;
        }
    }
    if !widened {
        return None;
    }
    let fixed = String::from_utf8(bytes).ok()?;
    (!fixed.chars().any(char::is_control)).then_some(fixed)
}

pub(crate) fn parse_records(
    records: &[UserOptions],
    budget: &mut hsf_core::Budget,
) -> Result<Vec<UserOptionRecord>, Error> {
    let mut result = Vec::new();
    for record in records {
        budget.charge_output(
            512 + record.node_id.len() as u64
                + record.source_record_id.len() as u64
                + record.text.source.domain_id.len() as u64
                + record.text.value.as_ref().map_or(0, |s| s.len() as u64 * 4),
        )?;
        let parsed = assignments(&record.text, budget)?;
        let (parsing_status, reason, mut assignments) = match parsed {
            Ok(assignments) => (Status::Complete, None, assignments),
            Err(reason) => (Status::Unsupported, Some(reason.into()), Vec::new()),
        };
        if record.text.encoding == "utf_16_le" {
            for a in &mut assignments {
                if let Some(fixed) = sign_extended_utf8(&a.value) {
                    budget.charge_output(fixed.len() as u64)?;
                    a.value = fixed;
                }
            }
        }
        result.push(UserOptionRecord {
            node_id: record.node_id.clone(),
            source_record_id: record.source_record_id.clone(),
            source: record.text.source.clone(),
            parsing_status,
            reason,
            assignments,
        });
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::sign_extended_utf8;

    fn widened(text: &str) -> String {
        text.bytes()
            .map(|b| {
                if b < 0x80 {
                    char::from(b)
                } else {
                    char::from_u32(0xff00 | u32::from(b)).unwrap()
                }
            })
            .collect()
    }

    #[test]
    fn sign_extended_utf8_recovers_only_the_widened_form() {
        assert_eq!(
            sign_extended_utf8(&widened("ピン_φ4")).as_deref(),
            Some("ピン_φ4")
        );
        assert_eq!(
            sign_extended_utf8(&widened("ベース板")).as_deref(),
            Some("ベース板")
        );
        // Plain ASCII and genuine UTF-16 text are left alone.
        assert_eq!(sign_extended_utf8("Pin Pair"), None);
        assert_eq!(sign_extended_utf8("ピン_φ4"), None);
        // Halfwidth katakana alone is not valid UTF-8 once narrowed.
        assert_eq!(sign_extended_utf8("ﾃｽﾄ"), None);
        // Fullwidth signs mixed with ASCII: narrowed bytes are not UTF-8 either.
        assert_eq!(sign_extended_utf8("a￠b"), None);
        // A widened control character is rejected.
        assert_eq!(sign_extended_utf8(&widened("\u{85}")), None);
    }
}

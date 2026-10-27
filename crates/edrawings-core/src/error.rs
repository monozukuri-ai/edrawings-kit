use crate::{Diagnostic, Status};
use std::fmt;

#[derive(Debug)]
pub enum Error {
    Format(Box<Diagnostic>),
    Io(std::io::Error),
}
impl Error {
    pub fn invalid(code: &str, stage: &str, message: &str) -> Self {
        Self::Format(Box::new(Diagnostic::new(
            code,
            Status::Invalid,
            stage,
            message,
        )))
    }
    pub fn unsupported(code: &str, stage: &str, message: &str) -> Self {
        Self::Format(Box::new(Diagnostic::new(
            code,
            Status::Unsupported,
            stage,
            message,
        )))
    }
    pub fn limit(code: &str, message: &str) -> Self {
        Self::Format(Box::new(Diagnostic::new(
            code,
            Status::LimitExceeded,
            "limits",
            message,
        )))
    }
    pub fn diagnostic(&self) -> Option<&Diagnostic> {
        if let Self::Format(d) = self {
            Some(d)
        } else {
            None
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Format(d) => write!(f, "{}: {}", d.code, d.message),
            Self::Io(e) => e.fmt(f),
        }
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}
impl From<hsf_core::HsfError> for Error {
    fn from(e: hsf_core::HsfError) -> Self {
        let d = e.diagnostic;
        let status = match d.classification {
            hsf_core::Status::LimitExceeded => Status::LimitExceeded,
            hsf_core::Status::Unsupported => Status::Unsupported,
            _ => Status::Invalid,
        };
        Self::Format(Box::new(Diagnostic::new(
            &d.code, status, &d.stage, &d.message,
        )))
    }
}

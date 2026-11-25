/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! IPA file format support, allowing it to be used as part of the guest
//! filesystem.
use crate::fs::{FsNode, GuestPath};
use crate::libc::time::{calendar_date_to_timestamp, time_t, tm};
use std::cell::{OnceCell, RefCell};
use std::fmt::Debug;
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};
use std::rc::Rc;
use zip::result::ZipError;
use zip::ZipArchive;

/// A helper struct to build an FsNode with files and directories coming in
/// arbitrary order. This is required, because ZIP files are allowed to store
/// entries in arbitrary order.
struct FsNodeBuilder {
    root: FsNode,
}

impl FsNodeBuilder {
    fn new() -> Self {
        Self {
            root: FsNode::dir(),
        }
    }

    fn find_or_make_directory(&mut self, path: &GuestPath) -> &mut FsNode {
        let mut current = &mut self.root;
        for part in path.as_str().split('/') {
            if part.is_empty() {
                continue;
            }
            assert_ne!(part, "..", "unexpected .. in path: {path:?}");
            let FsNode::Directory { children, .. } = current else {
                panic!("expected directory, got {current:?}");
            };

            let next = children.entry(part.to_string()).or_insert_with(FsNode::dir);
            current = next;
        }
        current
    }

    fn add_file(&mut self, path: &GuestPath, node: FsNode) {
        let (parent_name, file_name) = path.parent_and_file_name().unwrap();
        assert_ne!(file_name, "..", "unexpected .. in path: {path:?}");
        let dir = self.find_or_make_directory(parent_name);
        let FsNode::Directory { children, .. } = dir else {
            panic!("expected directory, got {dir:?}");
        };

        children.insert(file_name.to_string(), node);
    }

    fn add_directory(&mut self, path: &GuestPath) {
        self.find_or_make_directory(path);
    }

    fn build(self) -> FsNode {
        self.root
    }
}

/// Represents an open app bundle, either a directory or a zip file.
pub enum BundleData {
    HostDirectory(PathBuf),
    Zip {
        zip: ZipArchive<std::fs::File>,
        /// Path to the app bundle inside the zip file.
        /// It should be `"Payload/<app name>.app"` (no trailing slash!).
        bundle_path: String,
    },
}

impl BundleData {
    fn find_bundle_path_in_archive(zip: &mut ZipArchive<std::fs::File>) -> Result<String, String> {
        for i in 0..zip.len() {
            let file = zip
                .by_index(i)
                .map_err(|e| format!("Could not open IPA archive entry: {e}"))?;
            let path = file.name();
            if let Some(name) = path
                .strip_prefix("Payload/")
                .and_then(|path| path.split_once('/'))
                .and_then(|(name, _)| name.strip_suffix(".app"))
            {
                return Ok(format!("Payload/{name}.app"));
            }
        }
        Err("no app bundle found in the IPA archive".to_string())
    }

    pub fn bundle_name(&self) -> &str {
        match self {
            BundleData::HostDirectory(bundle_path) => {
                bundle_path.file_stem().unwrap().to_str().unwrap()
            }
            BundleData::Zip { bundle_path, .. } => bundle_path
                .rsplit_once('/')
                .unwrap()
                .1
                .strip_suffix(".app")
                .unwrap(),
        }
    }

    pub fn open_host_dir(path: &Path) -> Result<BundleData, String> {
        Ok(BundleData::HostDirectory(path.to_path_buf()))
    }

    pub fn open_ipa(path: &Path) -> Result<BundleData, String> {
        let file =
            std::fs::File::open(path).map_err(|e| format!("Could not open IPA file: {e}"))?;
        let mut zip =
            ZipArchive::new(file).map_err(|e| format!("Could not open IPA archive: {e}"))?;
        let bundle_path = Self::find_bundle_path_in_archive(&mut zip)?;
        Ok(BundleData::Zip { zip, bundle_path })
    }

    pub fn open_any(path: &Path) -> Result<BundleData, String> {
        if path.is_file()
            && path
                .extension()
                .map(|ext| ext.eq_ignore_ascii_case("ipa"))
                .unwrap_or(false)
        {
            Ok(Self::open_ipa(path)?)
        } else if path.is_dir() {
            Ok(Self::open_host_dir(path)?)
        } else {
            Err(format!(
                "{} is not a directory or an IPA file",
                path.display()
            ))
        }
    }

    pub(super) fn into_fs_node(self) -> FsNode {
        match self {
            BundleData::HostDirectory(path) => FsNode::from_host_dir(&path, false),
            BundleData::Zip { zip, bundle_path } => {
                let archive = Rc::new(RefCell::new(zip));

                let mut archive_guard = (*archive).borrow_mut();

                let mut builder = FsNodeBuilder::new();
                for i in 0..archive_guard.len() {
                    let file = archive_guard.by_index(i).unwrap(); // TODO: report IO error?
                    let name = file.name();
                    if let Some(path) = name.strip_prefix(&bundle_path) {
                        let path = GuestPath::new(path);
                        if file.is_dir() {
                            builder.add_directory(path);
                        } else {
                            builder.add_file(
                                path,
                                FsNode::bundle_zip_file(IpaFileRef {
                                    archive: archive.clone(),
                                    index: i,
                                    size: file.size(),
                                    modified: file.last_modified(),
                                    contents: OnceCell::new(),
                                }),
                            );
                        }
                    }
                }
                builder.build()
            }
        }
    }

    pub fn read_plist(&mut self) -> Result<Vec<u8>, String> {
        match self {
            BundleData::HostDirectory(path) => {
                std::fs::read(path.join("Info.plist")).map_err(|e| {
                    format!("Could not read Info.plist from the app bundle directory: {e}")
                })
            }
            BundleData::Zip { zip, bundle_path } => {
                let mut file = zip
                    .by_name(&format!("{bundle_path}/Info.plist"))
                    .map_err(|e| format!("Could not open Info.plist from the IPA archive: {e}"))?;
                let mut buf = Vec::new();
                file.read_to_end(&mut buf)
                    .map_err(|e| format!("Could not read Info.plist from the IPA archive: {e}"))?;
                Ok(buf)
            }
        }
    }
}

/// Shared (refcounted) copy of the decompressed version of a file in an IPA.
///
/// Seeking in compressed files is hard, so the simple solution is to read the
/// whole file into memory. This is shared so having multiple copies of the same
/// file open won't waste memory.
type DecompressedFile = Rc<[u8]>;

/// Represents a file inside an IPA bundle that can be opened.
#[derive(Debug)]
pub struct IpaFileRef {
    archive: Rc<RefCell<ZipArchive<std::fs::File>>>,
    index: usize,
    size: u64,
    modified: zip::DateTime,
    contents: OnceCell<DecompressedFile>,
}

impl IpaFileRef {
    pub fn open(&self) -> IpaFile {
        // Some games, like THPS2, use a single resource bundle file which is
        // opened each time a new game resource is being read.
        // As IPA is basically an archive, this pattern requires unzipping to be
        // done each time, which is extremely slow.
        // The solution here is to cache unzipped data in memory, which should
        // be OK as early iOS IPA files are relatively small in size.
        let contents = self.contents.get_or_init(|| {
            let mut archive = (*self.archive).borrow_mut();
            let mut file = match archive.by_index(self.index) {
                Ok(file) => file,
                Err(ZipError::Io(e)) => {
                    // this is a runtime error, which we __probably__ should not
                    // bubble up to the guest
                    panic!("IO error while opening file from IPA bundle: {e}")
                }
                // anything other than IO error is a bug in the code, we should
                // always have a valid index
                Err(e) => panic!("BUG: could not open file from IPA bundle: {e}"),
            };
            let mut buf = Vec::new();
            file.read_to_end(&mut buf).unwrap();
            Rc::from(buf)
        });
        IpaFile {
            file: Cursor::new(Rc::clone(contents)),
        }
    }

    pub fn get_last_modified(&self) -> time_t {
        let date = self.modified;
        calendar_date_to_timestamp(tm::from(
            date.year(),
            date.month(),
            date.day(),
            date.hour(),
            date.minute(),
            date.second(),
        ))
    }
    pub fn get_size(&self) -> u64 {
        self.size
    }
}

/// Represents an opened file in an IPA bundle.
pub struct IpaFile {
    file: Cursor<DecompressedFile>,
}

impl Debug for IpaFile {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IpaFile")
            .field("size", &self.file.get_ref().len())
            .finish()
    }
}

impl Read for IpaFile {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        self.file.read(buf)
    }
}

impl std::io::Seek for IpaFile {
    fn seek(&mut self, pos: std::io::SeekFrom) -> std::io::Result<u64> {
        self.file.seek(pos)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fs::FileLocation;
    use std::io::{Seek, SeekFrom, Write};
    use std::time::{SystemTime, UNIX_EPOCH};
    use zip::{write::FileOptions, CompressionMethod, DateTime, ZipWriter};

    #[test]
    fn ipa_metadata_leaves_contents_unopened() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("touchhle-ipa-{}-{nonce}.ipa", std::process::id()));
        let payload = b"0123456789";
        let options = FileOptions::default()
            .compression_method(CompressionMethod::Deflated)
            .last_modified_time(DateTime::from_date_and_time(2000, 1, 1, 0, 0, 0).unwrap());
        let mut writer = ZipWriter::new(std::fs::File::create_new(&path).unwrap());
        writer
            .start_file("Payload/Test.app/sample", options)
            .unwrap();
        writer.write_all(payload).unwrap();
        drop(writer.finish().unwrap());

        let bundle = BundleData::open_ipa(&path).unwrap().into_fs_node();
        let FsNode::Directory { children, .. } = &bundle else {
            panic!("expected bundle contents");
        };
        let FsNode::File {
            location: FileLocation::IpaFileRef(file),
            ..
        } = &children["sample"]
        else {
            panic!("expected an archived file");
        };
        assert_eq!(file.get_size(), payload.len() as u64);
        assert_eq!(file.get_last_modified(), 946_684_800);
        assert!(file.contents.get().is_none());

        let mut first = file.open();
        first.seek(SeekFrom::End(-2)).unwrap();
        let mut second = file.open();
        assert!(Rc::ptr_eq(first.file.get_ref(), second.file.get_ref()));
        let mut bytes = Vec::new();
        second.read_to_end(&mut bytes).unwrap();
        assert_eq!(bytes, payload);
        bytes.clear();
        first.read_to_end(&mut bytes).unwrap();
        assert_eq!(bytes, b"89");
        drop(bundle);
        std::fs::remove_file(path).unwrap();
    }
}

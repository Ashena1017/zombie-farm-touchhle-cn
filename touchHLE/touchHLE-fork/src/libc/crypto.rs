/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! CommonCrypto and friends

use crate::dyld::FunctionExports;
use crate::mem::{ConstVoidPtr, MutPtr};
use crate::{export_c_func, Environment};
use digest::Digest;
use md5::Md5;
use sha1::Sha1;
use sha2::Sha256;
use std::cell::RefCell;
use std::collections::HashMap;

thread_local! {
    static CC_MD5_OVERRIDES: RefCell<HashMap<(u32, u32), [u8; 16]>> = RefCell::new(HashMap::new());
    static CC_MD5_DIGEST_OVERRIDES: RefCell<HashMap<[u8; 16], [u8; 16]>> =
        RefCell::new(HashMap::new());
}

pub fn register_cc_md5_override(data: ConstVoidPtr, len: u32, digest: [u8; 16]) {
    CC_MD5_OVERRIDES.with(|overrides| {
        overrides.borrow_mut().insert((data.to_bits(), len), digest);
    });
}

pub fn register_cc_md5_override_for_bytes(
    env: &Environment,
    data: ConstVoidPtr,
    len: u32,
    digest: [u8; 16],
) {
    register_cc_md5_override(data, len, digest);

    let mut hasher = Md5::new();
    hasher.update(env.mem.bytes_at(data.cast(), len));
    let actual = hasher.finalize();
    let mut actual_digest = [0; 16];
    actual_digest.copy_from_slice(&actual[..]);

    CC_MD5_DIGEST_OVERRIDES.with(|overrides| {
        overrides.borrow_mut().insert(actual_digest, digest);
    });
}

fn CC_MD5(env: &mut Environment, data: ConstVoidPtr, len: u32, md: MutPtr<u8>) -> MutPtr<u8> {
    if let Some(digest) = zombie_farm_magic_md5_override(env, data, len) {
        env.mem.bytes_at_mut(md, 16).copy_from_slice(&digest);
        return md;
    }
    if let Some(digest) =
        CC_MD5_OVERRIDES.with(|overrides| overrides.borrow().get(&(data.to_bits(), len)).copied())
    {
        env.mem.bytes_at_mut(md, 16).copy_from_slice(&digest);
        return md;
    }
    let mut hasher = Md5::new();
    hasher.update(env.mem.bytes_at(data.cast(), len));
    let digest = hasher.finalize();
    let mut digest_bytes = [0; 16];
    digest_bytes.copy_from_slice(&digest[..]);
    if let Some(override_digest) =
        CC_MD5_DIGEST_OVERRIDES.with(|overrides| overrides.borrow().get(&digest_bytes).copied())
    {
        digest_bytes = override_digest;
    }
    env.mem.bytes_at_mut(md, 16).copy_from_slice(&digest_bytes);
    md
}

fn zombie_farm_magic_md5_override(
    env: &mut Environment,
    data: ConstVoidPtr,
    len: u32,
) -> Option<[u8; 16]> {
    if !(env
        .bundle
        .bundle_identifier()
        .starts_with("com.playforge.ZombieFarm")
        || env
            .bundle
            .bundle_identifier()
            .starts_with("com.playforge.ZFR"))
        || len != 47
    {
        return None;
    }

    let bytes = env.mem.bytes_at(data.cast(), len);
    if &bytes[32..] != b"ZombieFarmMagic" || !bytes[..32].iter().all(u8::is_ascii_hexdigit) {
        return None;
    }

    let mut digest = [0u8; 16];
    for (idx, byte) in digest.iter_mut().enumerate() {
        let start = idx * 2;
        let hex = std::str::from_utf8(&bytes[start..start + 2]).ok()?;
        *byte = u8::from_str_radix(hex, 16).ok()?;
    }
    Some(digest)
}

fn CC_SHA1(env: &mut Environment, data: ConstVoidPtr, len: u32, md: MutPtr<u8>) -> MutPtr<u8> {
    let mut hasher = Sha1::new();
    hasher.update(env.mem.bytes_at(data.cast(), len));
    let digest = hasher.finalize();
    env.mem.bytes_at_mut(md, 20).copy_from_slice(&digest[..]);
    md
}

fn CC_SHA256(env: &mut Environment, data: ConstVoidPtr, len: u32, md: MutPtr<u8>) -> MutPtr<u8> {
    let mut hasher = Sha256::new();
    hasher.update(env.mem.bytes_at(data.cast(), len));
    let digest = hasher.finalize();
    env.mem.bytes_at_mut(md, 32).copy_from_slice(&digest[..]);
    md
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CC_MD5(_, _, _)),
    export_c_func!(CC_SHA1(_, _, _)),
    export_c_func!(CC_SHA256(_, _, _)),
];

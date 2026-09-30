/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `CGFont.h`

use super::cg_data_provider::{CGDataProviderRef, CGDataProviderRelease, CGDataProviderRetain};
use crate::dyld::FunctionExports;
use crate::export_c_func;
use crate::frameworks::core_foundation::{CFRelease, CFRetain, CFTypeRef};
use crate::frameworks::foundation::ns_string::get_static_str;
use crate::objc::{id, nil, objc_classes, ClassExports, HostObject};
use crate::Environment;

pub type CGFontRef = CFTypeRef;

struct CGFontHostObject {
    provider: CGDataProviderRef,
}
impl HostObject for CGFontHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation _touchHLE_CGFont: NSObject

- (())dealloc {
    let provider = env.objc.borrow::<CGFontHostObject>(this).provider;
    CGDataProviderRelease(env, provider);
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};

fn CGFontCreateWithDataProvider(env: &mut Environment, provider: CGDataProviderRef) -> CGFontRef {
    if provider.is_null() {
        return nil;
    }

    CGDataProviderRetain(env, provider);
    let class = env.objc.get_known_class("_touchHLE_CGFont", &mut env.mem);
    env.objc
        .alloc_object(class, Box::new(CGFontHostObject { provider }), &mut env.mem)
}

fn CGFontRetain(env: &mut Environment, font: CGFontRef) -> CGFontRef {
    if !font.is_null() {
        CFRetain(env, font)
    } else {
        font
    }
}

fn CGFontRelease(env: &mut Environment, font: CGFontRef) {
    if !font.is_null() {
        CFRelease(env, font);
    }
}

fn CGFontCopyFullName(env: &mut Environment, font: CGFontRef) -> id {
    if font.is_null() {
        return nil;
    }
    get_static_str(env, "touchHLE")
}

fn CGFontCopyPostScriptName(env: &mut Environment, font: CGFontRef) -> id {
    if font.is_null() {
        return nil;
    }
    get_static_str(env, "touchHLE")
}

fn CGFontGetUnitsPerEm(_env: &mut Environment, font: CGFontRef) -> u32 {
    if font.is_null() {
        return 0;
    }
    1000
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(CGFontCreateWithDataProvider(_)),
    export_c_func!(CGFontRetain(_)),
    export_c_func!(CGFontRelease(_)),
    export_c_func!(CGFontCopyFullName(_)),
    export_c_func!(CGFontCopyPostScriptName(_)),
    export_c_func!(CGFontGetUnitsPerEm(_)),
];

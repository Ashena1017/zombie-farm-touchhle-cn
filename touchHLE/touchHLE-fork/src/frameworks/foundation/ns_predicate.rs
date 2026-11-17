/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSPredicate`.

use super::{ns_string, NSUInteger};
use crate::abi::VaList;
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, ClassExports, HostObject,
    NSZonePtr,
};

#[derive(Clone, Debug)]
enum PredicateKind {
    /// Fallback used by the previous implementation.
    AlwaysTrue,
    /// CCTableView uses equality to find a cell and inequalities to evict only
    /// cells outside the visible interval. Treating '<' or '>' as AlwaysTrue
    /// evicts the entire table on every scroll update.
    IndexComparison(IndexComparison, i64),
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum IndexComparison { Equal, NotEqual, Less, LessEqual, Greater, GreaterEqual }

impl IndexComparison {
    fn evaluate(self, actual: NSUInteger, expected: i64) -> bool {
        let actual = i64::from(actual);
        match self {
            Self::Equal => actual == expected,
            Self::NotEqual => actual != expected,
            Self::Less => actual < expected,
            Self::LessEqual => actual <= expected,
            Self::Greater => actual > expected,
            Self::GreaterEqual => actual >= expected,
        }
    }
}

fn index_comparison(format: &str) -> Option<(IndexComparison, &str)> {
    let expression = format.strip_prefix("idx")?;
    // Longest operators first; do not accept arbitrary expressions as an idx
    // comparison (e.g. compound predicates or another property containing idx).
    for (token, op) in [
        ("==", IndexComparison::Equal), ("!=", IndexComparison::NotEqual),
        ("<=", IndexComparison::LessEqual), (">=", IndexComparison::GreaterEqual),
        ("=", IndexComparison::Equal), ("<", IndexComparison::Less),
        (">", IndexComparison::Greater),
    ] {
        if let Some(rhs) = expression.strip_prefix(token) { return Some((op, rhs)); }
    }
    None
}

struct NSPredicateHostObject {
    /// `NSString *`
    format: id,
    kind: PredicateKind,
}
impl HostObject for NSPredicateHostObject {}

fn parse_predicate_kind(
    env: &mut crate::Environment,
    format: id,
    args: Option<VaList>,
) -> PredicateKind {
    if format == nil {
        return PredicateKind::AlwaysTrue;
    }

    let format_string = ns_string::to_rust_string(env, format).to_string();
    let compact = format_string
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();

    if let Some((op, rhs)) = index_comparison(&compact) {
        if matches!(rhs, "%d" | "%i" | "%ld" | "%li" | "%u" | "%lu") {
            if let Some(mut args) = args {
                let value = if matches!(rhs, "%u" | "%lu") {
                    i64::from(args.next::<NSUInteger>(env))
                } else {
                    i64::from(args.next::<super::NSInteger>(env))
                };
                return PredicateKind::IndexComparison(op, value);
            }
        } else if let Ok(value) = rhs.parse::<i64>() {
            return PredicateKind::IndexComparison(op, value);
        }
    }

    PredicateKind::AlwaysTrue
}

fn init_with_format_and_args(
    env: &mut crate::Environment,
    this: id,
    format: id,
    args: Option<VaList>,
) -> id {
    retain(env, format);
    let kind = parse_predicate_kind(env, format, args);
    let host_object = env.objc.borrow_mut::<NSPredicateHostObject>(this);
    host_object.format = format;
    host_object.kind = kind;
    this
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSPredicate: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSPredicateHostObject {
        format: nil,
        kind: PredicateKind::AlwaysTrue,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)predicateWithFormat:(id)format, ...args {
    let predicate: id = msg_class![env; NSPredicate alloc];
    let predicate = init_with_format_and_args(env, predicate, format, Some(args.start()));
    autorelease(env, predicate)
}

- (id)initWithFormat:(id)format, ...args {
    init_with_format_and_args(env, this, format, Some(args.start()))
}

- (id)predicateFormat {
    env.objc.borrow::<NSPredicateHostObject>(this).format
}

- (bool)evaluateWithObject:(id)object {
    let kind = env.objc.borrow::<NSPredicateHostObject>(this).kind.clone();
    match kind {
        PredicateKind::AlwaysTrue => {
            // Enough for games that use predicates to filter local config arrays.
            true
        }
        PredicateKind::IndexComparison(op, expected) => {
            if object == nil || !env.objc.object_has_method_named(&env.mem, object, "idx") {
                return false;
            }
            let actual: NSUInteger = msg![env; object idx];
            op.evaluate(actual, expected)
        }
    }
}

- (())dealloc {
    let host_object = env.objc.borrow_mut::<NSPredicateHostObject>(this);
    let format = std::mem::replace(&mut host_object.format, nil);
    release(env, format);
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_eviction_keeps_every_visible_cell() {
        for (first, last) in [(0, 5), (6, 17), (22, 27)] {
            let used: Vec<_> = (0..28).collect();
            let retained: Vec<_> = used.into_iter().filter(|&idx|
                !IndexComparison::Less.evaluate(idx, first)
                && !IndexComparison::Greater.evaluate(idx, last)).collect();
            assert_eq!(retained, (first as u32..=last as u32).collect::<Vec<_>>());
        }
    }

    #[test]
    fn comparison_boundaries_and_signed_arguments() {
        for (text, expected) in [("idx==%i", IndexComparison::Equal),
            ("idx!=%u", IndexComparison::NotEqual), ("idx<%i", IndexComparison::Less),
            ("idx<=5", IndexComparison::LessEqual), ("idx>%i", IndexComparison::Greater),
            ("idx>=-1", IndexComparison::GreaterEqual)] {
            assert_eq!(index_comparison(text).unwrap().0, expected);
        }
        assert!(!IndexComparison::Less.evaluate(0, -1));
        assert!(IndexComparison::Greater.evaluate(0, -1));
        assert!(IndexComparison::LessEqual.evaluate(5, 5));
        assert!(IndexComparison::GreaterEqual.evaluate(5, 5));
        assert!(!IndexComparison::NotEqual.evaluate(5, 5));
        assert!(IndexComparison::Equal.evaluate(u32::MAX, i64::from(u32::MAX)));
        assert_eq!(index_comparison("otheridx<%i"), None);
    }

    /// Optional integration check: executes the actual IPA's CCTableViewCell
    /// setters/getters with the production Foundation objects and varargs ABI.
    /// No game loop, window, save writes or input automation is involved.
    #[test]
    #[ignore = "requires ZFR_GUEST_TEST_IPA and the bundled runtime resources"]
    fn guest_table_predicates_keep_visible_cells() {
        let path = std::env::var("ZFR_GUEST_TEST_IPA").expect("set ZFR_GUEST_TEST_IPA");
        let bundle_data = crate::fs::BundleData::open_ipa(std::path::Path::new(&path)).unwrap();
        let (bundle, fs) = crate::bundle::Bundle::new_bundle_and_fs_from_host_path(bundle_data, true).unwrap();
        let mut options = crate::options::Options::default();
        options.headless = true;
        let mut environment = crate::Environment::new(bundle, fs, options, vec![]).unwrap();
        let mut coroutine = corosensei::Coroutine::new(|yielder, mut environment: crate::Environment| {
        environment.with_yielder(yielder, |env| {
        let pool: id = msg_class![env; NSAutoreleasePool new];
        let cells: id = msg_class![env; NSMutableArray new];
        for idx in 0..28u32 {
            let cell: id = msg_class![env; CCTableViewCell new];
            let _: () = msg![env; cell setIdx:idx];
            let _: () = msg![env; cells addObject:cell];
            release(env, cell);
        }
        for (format, bound, expected) in [("idx < %i", 6i32, 6u32),
            ("idx > %i", 17, 10), ("idx == %i", 12, 1),
            ("idx < %i", -1, 0), ("idx > %i", -1, 28)] {
            let text = ns_string::from_rust_string(env, format.to_string());
            let class = env.objc.get_known_class("NSPredicate", &mut env.mem);
            let selector = env.objc.lookup_selector("predicateWithFormat:").unwrap();
            let predicate: id = crate::objc::msg_send_no_type_checking(env, (class, selector, text, bound));
            let matches: id = msg![env; cells filteredArrayUsingPredicate:predicate];
            let count: NSUInteger = msg![env; matches count];
            assert_eq!(count, expected, "{format} {bound}");
            release(env, text);
        }
        release(env, cells);
        let _: () = msg![env; pool drain];
        });
        environment
        });
        loop {
            match coroutine.resume(environment) {
                corosensei::CoroutineResult::Return(env) => { drop(env); break; }
                corosensei::CoroutineResult::Yield(env) => {
                    assert_eq!(env.threads.len(), 1);
                    assert_eq!(env.threads[0].blocked_by, crate::environment::ThreadBlock::NotBlocked);
                    environment = env;
                }
            }
        }
    }
}

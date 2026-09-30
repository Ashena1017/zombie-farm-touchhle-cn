/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UITableViewController`.

use crate::frameworks::core_graphics::CGRect;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, msg_class, msg_super, nil, objc_classes, release,
    retain, ClassExports, NSZonePtr,
};

#[derive(Default)]
struct UITableViewControllerHostObject {
    superclass: super::UIViewControllerHostObject,
    /// `UITableView*`, currently represented by a UIView fallback if no table
    /// view class is needed by the app.
    table_view: id,
}
impl_HostObject_with_superclass!(UITableViewControllerHostObject);

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UITableViewController: UIViewController

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UITableViewControllerHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (())dealloc {
    let table_view = env.objc.borrow::<UITableViewControllerHostObject>(this).table_view;
    release(env, table_view);
    msg_super![env; this dealloc]
}

- (())loadView {
    let screen: id = msg_class![env; UIScreen mainScreen];
    let app_frame: CGRect = msg![env; screen applicationFrame];
    let view: id = msg_class![env; UIView alloc];
    let view: id = msg![env; view initWithFrame:app_frame];
    () = msg![env; this setTableView:view];
    () = msg![env; this setView:view];
    release(env, view);
}

- (id)tableView {
    let table_view = env.objc.borrow::<UITableViewControllerHostObject>(this).table_view;
    if table_view == nil {
        () = msg![env; this loadView];
        env.objc.borrow::<UITableViewControllerHostObject>(this).table_view
    } else {
        table_view
    }
}

- (())setTableView:(id)table_view {
    retain(env, table_view);
    let old = std::mem::replace(
        &mut env.objc.borrow_mut::<UITableViewControllerHostObject>(this).table_view,
        table_view,
    );
    release(env, old);
}

@end

};

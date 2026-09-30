/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UITableView` and `UITableViewCell`.

use crate::frameworks::core_graphics::{CGFloat, CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::ns_array;
use crate::frameworks::foundation::NSInteger;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, msg_class, msg_super, nil, objc_classes, release,
    retain, ClassExports, NSZonePtr, SEL,
};

type UITableViewStyle = NSInteger;

struct UITableViewHostObject {
    superclass: super::UIScrollViewHostObject,
    data_source: id,
    table_header_view: id,
    table_footer_view: id,
    background_view: id,
    row_height: CGFloat,
    style: UITableViewStyle,
    editing: bool,
    allows_selection: bool,
    selected_index_path: id,
    update_depth: usize,
    pending_reload: bool,
    /// Views materialized from the data source by the experimental table
    /// renderer. The table hierarchy and this vector each own one retain so
    /// that an app removing a generated view cannot leave a dangling pointer.
    rendered_views: Vec<id>,
}
impl_HostObject_with_superclass!(UITableViewHostObject);
impl Default for UITableViewHostObject {
    fn default() -> Self {
        Self {
            superclass: Default::default(),
            data_source: nil,
            table_header_view: nil,
            table_footer_view: nil,
            background_view: nil,
            row_height: 44.0,
            style: 0,
            editing: false,
            allows_selection: true,
            selected_index_path: nil,
            update_depth: 0,
            pending_reload: false,
            rendered_views: Vec::new(),
        }
    }
}

fn responds_to(env: &mut crate::Environment, object: id, selector_name: &str) -> bool {
    if object == nil {
        return false;
    }
    let selector: SEL = env
        .objc
        .register_host_selector(selector_name.to_string(), &mut env.mem);
    msg![env; object respondsToSelector:selector]
}

fn clear_rendered_views(env: &mut crate::Environment, table_view: id) {
    let views = std::mem::take(
        &mut env
            .objc
            .borrow_mut::<UITableViewHostObject>(table_view)
            .rendered_views,
    );
    for view in views {
        let superview: id = msg![env; view superview];
        if superview == table_view {
            () = msg![env; view removeFromSuperview];
        }
        release(env, view);
    }
}

fn remember_rendered_view(env: &mut crate::Environment, table_view: id, view: id) {
    retain(env, view);
    env.objc
        .borrow_mut::<UITableViewHostObject>(table_view)
        .rendered_views
        .push(view);
}

fn bind_cell_to_row(env: &mut crate::Environment, cell: id, table_view: id, index_path: id) {
    retain(env, index_path);
    let old_index_path = {
        let host = env.objc.borrow_mut::<UITableViewCellHostObject>(cell);
        host.table_view = table_view;
        std::mem::replace(&mut host.index_path, index_path)
    };
    release(env, old_index_path);
}

fn select_cell_row(env: &mut crate::Environment, cell: id) {
    let (table_view, index_path) = {
        let host = env.objc.borrow::<UITableViewCellHostObject>(cell);
        (host.table_view, host.index_path)
    };
    if table_view == nil || index_path == nil {
        return;
    }
    if !env
        .objc
        .borrow::<UITableViewHostObject>(table_view)
        .allows_selection
    {
        return;
    }

    retain(env, index_path);
    let old_index_path = {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(table_view);
        std::mem::replace(&mut host.selected_index_path, index_path)
    };
    release(env, old_index_path);
    () = msg![env; cell setSelected:true animated:true];

    let delegate: id = msg![env; table_view delegate];
    if responds_to(env, delegate, "tableView:didSelectRowAtIndexPath:") {
        let section: i32 = msg![env; index_path section];
        let row: i32 = msg![env; index_path row];
        log!("ZombieFarm UITableView selected section {section} row {row}");
        () = msg![env; delegate tableView:table_view didSelectRowAtIndexPath:index_path];
    }
}

fn zombie_farm_online_table_rendering_enabled(env: &crate::Environment) -> bool {
    let bundle_id = env.bundle.bundle_identifier();
    (bundle_id.starts_with("com.playforge.ZombieFarm")
        || bundle_id.starts_with("com.playforge.ZFR"))
        && std::env::var_os("TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL").is_some()
}

fn schedule_table_layout(env: &mut crate::Environment, table_view: id) {
    if zombie_farm_online_table_rendering_enabled(env) {
        // UIView::setNeedsLayout currently calls layoutSubviews immediately.
        // That is unsafe for Zombie Farm's social tables: acceptGift mutates
        // its model between beginUpdates/endUpdates, and a synchronous layout
        // re-enters the data source before acceptGift has returned. Queue the
        // layout on the main run loop to match UIKit's deferred semantics.
        let layout_selector = env.objc.lookup_selector("layoutSubviews").unwrap();
        () = msg![env; table_view performSelectorOnMainThread:layout_selector
                       withObject:nil
                       waitUntilDone:false];
    } else {
        () = msg![env; table_view setNeedsLayout];
    }
}

fn request_table_reload(env: &mut crate::Environment, table_view: id) {
    // UIKit applies reloads during a later layout pass. In particular, do not
    // call a Zombie Farm data source synchronously from reloadData or a row
    // update: the game's social controllers can still be unwinding those
    // methods while the fight scene is being created, and re-entering guest
    // code here can corrupt the saved ARM continuation.
    env.objc
        .borrow_mut::<UITableViewHostObject>(table_view)
        .pending_reload = true;
    schedule_table_layout(env, table_view);
}

fn render_pending_table_reload(env: &mut crate::Environment, table_view: id) {
    if env.current_thread != 0 {
        return;
    }
    let render_now = {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(table_view);
        if host.update_depth == 0 && host.pending_reload {
            host.pending_reload = false;
            true
        } else {
            false
        }
    };
    if render_now && zombie_farm_online_table_rendering_enabled(env) {
        render_data_source_views(env, table_view);
    }
}

/// Materialize the rows requested by a UITableView data source. touchHLE's
/// historical UITableView stub only invalidated layout from reloadData, so the
/// app could report rows without ever being asked to create a cell. Keep this
/// initial renderer behind Zombie Farm's opt-in online mode while it matures.
///
/// Data source and delegate callbacks are UIKit work and must stay on the main
/// thread. Zombie Farm performs network completion work on guest pthreads; if
/// those threads synchronously materialize cells, a main-thread table update can
/// interleave with the same controller and corrupt its guest execution state.
fn render_data_source_views(env: &mut crate::Environment, table_view: id) {
    assert_eq!(env.current_thread, 0);
    clear_rendered_views(env, table_view);

    let data_source: id = msg![env; table_view dataSource];
    if data_source == nil
        || !responds_to(env, data_source, "tableView:numberOfRowsInSection:")
        || !responds_to(env, data_source, "tableView:cellForRowAtIndexPath:")
    {
        return;
    }

    let delegate: id = msg![env; table_view delegate];
    let bounds: CGRect = msg![env; table_view bounds];
    let width = bounds.size.width;
    let default_row_height: CGFloat = msg![env; table_view rowHeight];
    let sections: NSInteger = if responds_to(env, data_source, "numberOfSectionsInTableView:") {
        msg![env; data_source numberOfSectionsInTableView:table_view]
    } else {
        1
    };
    let sections = sections.max(0);
    let has_header_height = responds_to(env, delegate, "tableView:heightForHeaderInSection:");
    let has_header_view = responds_to(env, delegate, "tableView:viewForHeaderInSection:");
    let has_row_height = responds_to(env, delegate, "tableView:heightForRowAtIndexPath:");

    let mut y = 0.0;
    let mut rendered_rows = 0;
    for section in 0..sections {
        let header_height: CGFloat = if has_header_height {
            msg![env; delegate tableView:table_view heightForHeaderInSection:section]
        } else {
            0.0
        };
        if has_header_view && header_height > 0.0 {
            let header: id =
                msg![env; delegate tableView:table_view viewForHeaderInSection:section];
            if header != nil {
                let frame = CGRect {
                    origin: CGPoint { x: 0.0, y },
                    size: CGSize {
                        width,
                        height: header_height,
                    },
                };
                () = msg![env; header setFrame:frame];
                remember_rendered_view(env, table_view, header);
                () = msg![env; table_view addSubview:header];
            }
            y += header_height;
        }

        let rows: NSInteger =
            msg![env; data_source tableView:table_view numberOfRowsInSection:section];
        for row in 0..rows.max(0) {
            let index_path: id = msg_class![env; NSIndexPath indexPathForRow:row inSection:section];
            let row_height: CGFloat = if has_row_height {
                msg![env; delegate tableView:table_view heightForRowAtIndexPath:index_path]
            } else {
                default_row_height
            };
            let cell: id =
                msg![env; data_source tableView:table_view cellForRowAtIndexPath:index_path];
            if cell != nil {
                let frame = CGRect {
                    origin: CGPoint { x: 0.0, y },
                    size: CGSize {
                        width,
                        height: row_height,
                    },
                };
                () = msg![env; cell setFrame:frame];
                bind_cell_to_row(env, cell, table_view, index_path);
                remember_rendered_view(env, table_view, cell);
                () = msg![env; table_view addSubview:cell];
                rendered_rows += 1;
            }
            y += row_height.max(0.0);
        }
    }
    let content_size = CGSize { width, height: y };
    () = msg![env; table_view setContentSize:content_size];
    log!("ZombieFarm UITableView materialized {rendered_rows} row(s) across {sections} section(s)");
}

struct UITableViewCellHostObject {
    superclass: super::super::UIViewHostObject,
    reuse_identifier: id,
    content_view: id,
    text_label: id,
    detail_text_label: id,
    image_view: id,
    background_view: id,
    selected_background_view: id,
    selection_style: NSInteger,
    table_view: id,
    index_path: id,
    selected: bool,
}
impl_HostObject_with_superclass!(UITableViewCellHostObject);
impl Default for UITableViewCellHostObject {
    fn default() -> Self {
        Self {
            superclass: Default::default(),
            reuse_identifier: nil,
            content_view: nil,
            text_label: nil,
            detail_text_label: nil,
            image_view: nil,
            background_view: nil,
            selected_background_view: nil,
            // UITableViewCellSelectionStyleBlue is UIKit's historical default.
            selection_style: 1,
            table_view: nil,
            index_path: nil,
            selected: false,
        }
    }
}

fn ensure_default_subviews(env: &mut crate::Environment, this: id) {
    if env
        .objc
        .borrow::<UITableViewCellHostObject>(this)
        .content_view
        != nil
    {
        return;
    }

    let bounds: CGRect = msg![env; this bounds];

    let content_view: id = msg_class![env; UIView alloc];
    let content_view: id = msg![env; content_view initWithFrame:bounds];

    let image_view: id = msg_class![env; UIImageView alloc];
    let image_view: id = msg![env; image_view initWithFrame:bounds];

    let text_label: id = msg_class![env; UILabel alloc];
    let text_label: id = msg![env; text_label initWithFrame:bounds];
    () = msg![env; text_label setBackgroundColor:nil];

    let detail_text_label: id = msg_class![env; UILabel alloc];
    let detail_text_label: id = msg![env; detail_text_label initWithFrame:bounds];
    () = msg![env; detail_text_label setBackgroundColor:nil];

    () = msg![env; content_view addSubview:image_view];
    () = msg![env; content_view addSubview:text_label];
    () = msg![env; content_view addSubview:detail_text_label];
    () = msg![env; this addSubview:content_view];

    {
        let host = env.objc.borrow_mut::<UITableViewCellHostObject>(this);
        host.content_view = content_view;
        host.image_view = image_view;
        host.text_label = text_label;
        host.detail_text_label = detail_text_label;
    }
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UITableView: UIScrollView

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UITableViewHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (id)initWithFrame:(CGRect)frame {
    let this: id = msg![env; this initWithFrame:frame style:0];
    this
}

- (id)initWithFrame:(CGRect)frame style:(UITableViewStyle)style {
    let this: id = msg_super![env; this initWithFrame:frame];
    let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
    host.style = style;
    host.row_height = 44.0;
    this
}

- (id)initWithCoder:(id)coder {
    let this: id = msg_super![env; this initWithCoder:coder];
    env.objc.borrow_mut::<UITableViewHostObject>(this).row_height = 44.0;
    this
}

- (())dealloc {
    let UITableViewHostObject {
        superclass: _,
        data_source: _,
        table_header_view,
        table_footer_view,
        background_view,
        row_height: _,
        style: _,
        editing: _,
        allows_selection: _,
        selected_index_path,
        update_depth: _,
        pending_reload: _,
        rendered_views,
    } = std::mem::take(env.objc.borrow_mut(this));
    for view in rendered_views {
        release(env, view);
    }
    release(env, table_header_view);
    release(env, table_footer_view);
    release(env, background_view);
    release(env, selected_index_path);
    msg_super![env; this dealloc]
}

- (id)dataSource {
    env.objc.borrow::<UITableViewHostObject>(this).data_source
}
- (())setDataSource:(id)data_source {
    env.objc.borrow_mut::<UITableViewHostObject>(this).data_source = data_source;
}

- (CGFloat)rowHeight {
    env.objc.borrow::<UITableViewHostObject>(this).row_height
}
- (())setRowHeight:(CGFloat)row_height {
    env.objc.borrow_mut::<UITableViewHostObject>(this).row_height = row_height;
}

- (UITableViewStyle)style {
    env.objc.borrow::<UITableViewHostObject>(this).style
}

- (bool)isEditing {
    env.objc.borrow::<UITableViewHostObject>(this).editing
}
- (())setEditing:(bool)editing {
    env.objc.borrow_mut::<UITableViewHostObject>(this).editing = editing;
}
- (())setEditing:(bool)editing animated:(bool)_animated {
    env.objc.borrow_mut::<UITableViewHostObject>(this).editing = editing;
}

- (bool)allowsSelection {
    env.objc.borrow::<UITableViewHostObject>(this).allows_selection
}
- (())setAllowsSelection:(bool)allows_selection {
    env.objc.borrow_mut::<UITableViewHostObject>(this).allows_selection = allows_selection;
}

- (id)tableHeaderView {
    env.objc.borrow::<UITableViewHostObject>(this).table_header_view
}
- (())setTableHeaderView:(id)view {
    let old = {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
        std::mem::replace(&mut host.table_header_view, view)
    };
    retain(env, view);
    release(env, old);
    if view != nil {
        () = msg![env; this addSubview:view];
    }
}

- (id)tableFooterView {
    env.objc.borrow::<UITableViewHostObject>(this).table_footer_view
}
- (())setTableFooterView:(id)view {
    let old = {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
        std::mem::replace(&mut host.table_footer_view, view)
    };
    retain(env, view);
    release(env, old);
    if view != nil {
        () = msg![env; this addSubview:view];
    }
}

- (id)backgroundView {
    env.objc.borrow::<UITableViewHostObject>(this).background_view
}
- (())setBackgroundView:(id)view {
    let old = {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
        std::mem::replace(&mut host.background_view, view)
    };
    retain(env, view);
    release(env, old);
    if view != nil {
        () = msg![env; this addSubview:view];
    }
}

- (id)visibleCells {
    ns_array::from_vec(env, Vec::new())
}

- (id)indexPathForSelectedRow {
    env.objc.borrow::<UITableViewHostObject>(this).selected_index_path
}

- (id)dequeueReusableCellWithIdentifier:(id)_reuse_identifier {
    nil
}
- (id)dequeueReusableCellWithIdentifier:(id)_reuse_identifier forIndexPath:(id)_index_path {
    nil
}

- (())reloadData {
    request_table_reload(env, this);
}

- (())beginUpdates {
    let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
    host.update_depth = host.update_depth.saturating_add(1);
    // Even a batch without explicit row operations may change delegate-provided
    // row heights, so refresh when the outermost batch ends.
    host.pending_reload = true;
}

- (())endUpdates {
    {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
        if host.update_depth > 0 {
            host.update_depth -= 1;
        }
    }
    schedule_table_layout(env, this);
}

- (())insertRowsAtIndexPaths:(id)_index_paths withRowAnimation:(NSInteger)_animation {
    request_table_reload(env, this);
}

- (())deleteRowsAtIndexPaths:(id)_index_paths withRowAnimation:(NSInteger)_animation {
    request_table_reload(env, this);
}

- (())reloadRowsAtIndexPaths:(id)_index_paths withRowAnimation:(NSInteger)_animation {
    request_table_reload(env, this);
}

- (())layoutSubviews {
    render_pending_table_reload(env, this);
    msg_super![env; this layoutSubviews]
}

- (())selectRowAtIndexPath:(id)index_path animated:(bool)_animated scrollPosition:(NSInteger)_scroll_position {
    retain(env, index_path);
    let old_index_path = {
        let host = env.objc.borrow_mut::<UITableViewHostObject>(this);
        std::mem::replace(&mut host.selected_index_path, index_path)
    };
    release(env, old_index_path);
}
- (())deselectRowAtIndexPath:(id)index_path animated:(bool)_animated {
    let selected_index_path = env.objc.borrow::<UITableViewHostObject>(this).selected_index_path;
    if selected_index_path != nil {
        let selected_section: i32 = msg![env; selected_index_path section];
        let selected_row: i32 = msg![env; selected_index_path row];
        let section: i32 = msg![env; index_path section];
        let row: i32 = msg![env; index_path row];
        if selected_section == section && selected_row == row {
            env.objc.borrow_mut::<UITableViewHostObject>(this).selected_index_path = nil;
            release(env, selected_index_path);
        }
    }
}
- (())scrollToRowAtIndexPath:(id)_index_path atScrollPosition:(NSInteger)_scroll_position animated:(bool)_animated {
}

- (())setSeparatorStyle:(NSInteger)_separator_style {
}
- (())setSectionHeaderHeight:(CGFloat)_height {
}
- (())setSectionFooterHeight:(CGFloat)_height {
}
- (())setAllowsSelectionDuringEditing:(bool)_allows_selection_during_editing {
}

@end

@implementation UITableViewCell: UIView

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UITableViewCellHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (id)initWithFrame:(CGRect)frame {
    let this: id = msg_super![env; this initWithFrame:frame];
    ensure_default_subviews(env, this);
    this
}

- (id)initWithStyle:(NSInteger)_style reuseIdentifier:(id)reuse_identifier {
    let frame = CGRect::default();
    let this: id = msg_super![env; this initWithFrame:frame];
    ensure_default_subviews(env, this);
    retain(env, reuse_identifier);
    let old = {
        let host = env.objc.borrow_mut::<UITableViewCellHostObject>(this);
        std::mem::replace(&mut host.reuse_identifier, reuse_identifier)
    };
    release(env, old);
    this
}

- (())dealloc {
    let UITableViewCellHostObject {
        superclass: _,
        reuse_identifier,
        content_view,
        text_label,
        detail_text_label,
        image_view,
        background_view,
        selected_background_view,
        selection_style: _,
        table_view: _,
        index_path,
        selected: _,
    } = std::mem::take(env.objc.borrow_mut(this));
    release(env, reuse_identifier);
    release(env, content_view);
    release(env, text_label);
    release(env, detail_text_label);
    release(env, image_view);
    release(env, background_view);
    release(env, selected_background_view);
    release(env, index_path);
    msg_super![env; this dealloc]
}

- (id)reuseIdentifier {
    env.objc.borrow::<UITableViewCellHostObject>(this).reuse_identifier
}

- (id)contentView {
    ensure_default_subviews(env, this);
    env.objc.borrow::<UITableViewCellHostObject>(this).content_view
}

- (id)textLabel {
    ensure_default_subviews(env, this);
    env.objc.borrow::<UITableViewCellHostObject>(this).text_label
}

- (id)detailTextLabel {
    ensure_default_subviews(env, this);
    env.objc.borrow::<UITableViewCellHostObject>(this).detail_text_label
}

- (id)imageView {
    ensure_default_subviews(env, this);
    env.objc.borrow::<UITableViewCellHostObject>(this).image_view
}

- (id)backgroundView {
    env.objc.borrow::<UITableViewCellHostObject>(this).background_view
}
- (())setBackgroundView:(id)view {
    let old = {
        let host = env.objc.borrow_mut::<UITableViewCellHostObject>(this);
        std::mem::replace(&mut host.background_view, view)
    };
    retain(env, view);
    release(env, old);
    if view != nil {
        () = msg![env; this insertSubview:view atIndex:0i32];
    }
}

- (id)selectedBackgroundView {
    env.objc.borrow::<UITableViewCellHostObject>(this).selected_background_view
}
- (())setSelectedBackgroundView:(id)view {
    let old = {
        let host = env.objc.borrow_mut::<UITableViewCellHostObject>(this);
        std::mem::replace(&mut host.selected_background_view, view)
    };
    retain(env, view);
    release(env, old);
    if view != nil {
        () = msg![env; this insertSubview:view atIndex:0i32];
        () = msg![env; view setHidden:true];
    }
}

- (NSInteger)selectionStyle {
    env.objc.borrow::<UITableViewCellHostObject>(this).selection_style
}
- (())setSelectionStyle:(NSInteger)style {
    env.objc.borrow_mut::<UITableViewCellHostObject>(this).selection_style = style;
}

- (())prepareForReuse {
}
- (bool)isSelected {
    env.objc.borrow::<UITableViewCellHostObject>(this).selected
}
- (())setSelected:(bool)selected {
    () = msg![env; this setSelected:selected animated:false];
}
- (())setSelected:(bool)selected animated:(bool)_animated {
    let selected_background_view = {
        let host = env.objc.borrow_mut::<UITableViewCellHostObject>(this);
        host.selected = selected;
        host.selected_background_view
    };
    if selected_background_view != nil {
        let hidden = !selected;
        () = msg![env; selected_background_view setHidden:hidden];
    }
}
- (())setHighlighted:(bool)_highlighted {
}
- (())setHighlighted:(bool)_highlighted animated:(bool)_animated {
}

- (())touchesEnded:(id)touches withEvent:(id)_event {
    let touch: id = msg![env; touches anyObject];
    if touch == nil {
        return;
    }
    let point: CGPoint = msg![env; touch locationInView:this];
    let inside: bool = msg![env; this pointInside:point withEvent:nil];
    if inside {
        select_cell_row(env, this);
    }
}

@end

};

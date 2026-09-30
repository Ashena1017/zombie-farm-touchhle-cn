/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Small `libsqlite3.dylib` compatibility layer backed by real SQLite.

use crate::dyld::{export_c_func, FunctionExports, HostDylib};
use crate::fs::{GuestOpenOptions, GuestPath};
use crate::mem::{guest_size_of, ConstPtr, ConstVoidPtr, MutPtr, MutVoidPtr, Ptr};
use crate::Environment;
use rusqlite::{
    params_from_iter,
    types::{Value, ValueRef},
    Connection,
};
use std::collections::HashMap;

const SQLITE_OK: i32 = 0;
const SQLITE_ERROR: i32 = 1;
const SQLITE_ROW: i32 = 100;
const SQLITE_DONE: i32 = 101;
const SQLITE_INTEGER: i32 = 1;
const SQLITE_FLOAT: i32 = 2;
const SQLITE_TEXT: i32 = 3;
const SQLITE_BLOB: i32 = 4;
const SQLITE_NULL: i32 = 5;

pub const DYLIB: HostDylib = HostDylib {
    path: "/usr/lib/libsqlite3.dylib",
    aliases: &["/usr/lib/libsqlite3.0.dylib"],
    class_exports: &[],
    constant_exports: &[],
    function_exports: &[FUNCTIONS],
};

#[derive(Default)]
pub struct State {
    databases: HashMap<MutVoidPtr, Database>,
    statements: HashMap<MutVoidPtr, Statement>,
    tables: HashMap<MutPtr<ConstPtr<u8>>, Vec<MutVoidPtr>>,
}

struct Database {
    connection: Connection,
    last_error: String,
    changes: i32,
    last_insert_rowid: i64,
}

#[derive(Clone, Debug)]
enum CellValue {
    Null,
    Integer(i64),
    Float(f64),
    Text(String),
    Blob(Vec<u8>),
}

impl CellValue {
    fn from_value_ref(value: ValueRef<'_>) -> Self {
        match value {
            ValueRef::Null => Self::Null,
            ValueRef::Integer(value) => Self::Integer(value),
            ValueRef::Real(value) => Self::Float(value),
            ValueRef::Text(value) => Self::Text(String::from_utf8_lossy(value).into_owned()),
            ValueRef::Blob(value) => Self::Blob(value.to_vec()),
        }
    }

    fn to_sqlite_value(&self) -> Value {
        match self {
            Self::Null => Value::Null,
            Self::Integer(value) => Value::Integer(*value),
            Self::Float(value) => Value::Real(*value),
            Self::Text(value) => Value::Text(value.clone()),
            Self::Blob(value) => Value::Blob(value.clone()),
        }
    }

    fn sqlite_type(&self) -> i32 {
        match self {
            Self::Null => SQLITE_NULL,
            Self::Integer(_) => SQLITE_INTEGER,
            Self::Float(_) => SQLITE_FLOAT,
            Self::Text(_) => SQLITE_TEXT,
            Self::Blob(_) => SQLITE_BLOB,
        }
    }

    fn as_i64(&self) -> i64 {
        match self {
            Self::Null => 0,
            Self::Integer(value) => *value,
            Self::Float(value) => *value as i64,
            Self::Text(value) => value.parse().unwrap_or_default(),
            Self::Blob(_) => 0,
        }
    }

    fn as_f64(&self) -> f64 {
        match self {
            Self::Null => 0.0,
            Self::Integer(value) => *value as f64,
            Self::Float(value) => *value,
            Self::Text(value) => value.parse().unwrap_or_default(),
            Self::Blob(_) => 0.0,
        }
    }

    fn as_text_bytes(&self) -> Vec<u8> {
        match self {
            Self::Null => Vec::new(),
            Self::Integer(value) => value.to_string().into_bytes(),
            Self::Float(value) => value.to_string().into_bytes(),
            Self::Text(value) => value.as_bytes().to_vec(),
            Self::Blob(value) => value.clone(),
        }
    }

    fn as_blob_bytes(&self) -> Vec<u8> {
        match self {
            Self::Blob(value) => value.clone(),
            _ => self.as_text_bytes(),
        }
    }
}

struct Statement {
    db: MutVoidPtr,
    sql: String,
    bindings: Vec<CellValue>,
    columns: Vec<String>,
    rows: Vec<Vec<CellValue>>,
    next_row: usize,
    current_row: Option<Vec<CellValue>>,
    executed: bool,
    column_allocations: Vec<MutVoidPtr>,
}

fn set_last_error(env: &mut Environment, db: MutVoidPtr, error: impl Into<String>) {
    if let Some(database) = env.framework_state.sqlite.databases.get_mut(&db) {
        database.last_error = error.into();
    }
}

fn clear_column_allocations(env: &mut Environment, stmt: MutVoidPtr) {
    let allocations = env
        .framework_state
        .sqlite
        .statements
        .get_mut(&stmt)
        .map(|statement| std::mem::take(&mut statement.column_allocations))
        .unwrap_or_default();
    for allocation in allocations {
        env.mem.free(allocation);
    }
}

fn current_cell(env: &Environment, stmt: MutVoidPtr, column: i32) -> Option<CellValue> {
    let statement = env.framework_state.sqlite.statements.get(&stmt)?;
    let row = statement.current_row.as_ref()?;
    row.get(column as usize).cloned()
}

fn alloc_stmt_buffer(env: &mut Environment, stmt: MutVoidPtr, bytes: &[u8]) -> MutPtr<u8> {
    let allocation = env.mem.alloc_and_write_cstr(bytes);
    if let Some(statement) = env.framework_state.sqlite.statements.get_mut(&stmt) {
        statement.column_allocations.push(allocation.cast());
    }
    allocation
}

fn sqlite3_open(env: &mut Environment, filename: ConstPtr<u8>, db_out: MutPtr<MutVoidPtr>) -> i32 {
    let filename = if filename.is_null() {
        ":memory:".to_string()
    } else {
        env.mem
            .cstr_at_utf8(filename)
            .unwrap_or("<invalid>")
            .to_string()
    };

    let connection = if filename == ":memory:" {
        match Connection::open_in_memory() {
            Ok(connection) => connection,
            Err(error) => {
                log!("sqlite3_open({filename:?}) failed: {error}");
                env.mem.write(db_out, Ptr::null());
                return SQLITE_ERROR;
            }
        }
    } else {
        let guest_path = GuestPath::new(&filename);
        let mut options = GuestOpenOptions::new();
        options.read().write().create();
        match env.fs.open_with_options(guest_path, options) {
            Ok(file) => drop(file),
            Err(()) => {
                log!("sqlite3_open({filename:?}) failed: file is not writable in guest filesystem");
                env.mem.write(db_out, Ptr::null());
                return SQLITE_ERROR;
            }
        }

        let Some(host_path) = env.fs.host_path_for_file(guest_path) else {
            log!("sqlite3_open({filename:?}) failed: no writable host path");
            env.mem.write(db_out, Ptr::null());
            return SQLITE_ERROR;
        };

        match Connection::open(&host_path) {
            Ok(connection) => {
                log_dbg!("sqlite3_open({filename:?}) -> live SQLite database at {host_path:?}");
                connection
            }
            Err(error) => {
                log!("sqlite3_open({filename:?}) failed at {host_path:?}: {error}");
                env.mem.write(db_out, Ptr::null());
                return SQLITE_ERROR;
            }
        }
    };

    let handle = env.mem.alloc(1);
    env.mem.write(db_out, handle);
    env.framework_state.sqlite.databases.insert(
        handle,
        Database {
            connection,
            last_error: "not an error".to_string(),
            changes: 0,
            last_insert_rowid: 0,
        },
    );
    if filename == ":memory:" {
        log_dbg!("sqlite3_open({filename:?}) -> live in-memory SQLite database");
    }
    SQLITE_OK
}

fn sqlite3_open_v2(
    env: &mut Environment,
    filename: ConstPtr<u8>,
    db_out: MutPtr<MutVoidPtr>,
    _flags: i32,
    _vfs: ConstPtr<u8>,
) -> i32 {
    sqlite3_open(env, filename, db_out)
}

fn sqlite3_close(env: &mut Environment, db: MutVoidPtr) -> i32 {
    let statements: Vec<MutVoidPtr> = env
        .framework_state
        .sqlite
        .statements
        .iter()
        .filter_map(|(&stmt, statement)| (statement.db == db).then_some(stmt))
        .collect();
    for stmt in statements {
        let _ = sqlite3_finalize(env, stmt);
    }

    if env.framework_state.sqlite.databases.remove(&db).is_some() {
        env.mem.free(db);
    }
    SQLITE_OK
}

fn sqlite3_prepare_v2(
    env: &mut Environment,
    db: MutVoidPtr,
    sql: ConstPtr<u8>,
    _n_byte: i32,
    stmt_out: MutPtr<MutVoidPtr>,
    tail_out: MutPtr<ConstPtr<u8>>,
) -> i32 {
    let sql_text = if sql.is_null() {
        String::new()
    } else {
        match env.mem.cstr_at_utf8(sql) {
            Ok(sql) => sql.to_string(),
            Err(_) => {
                set_last_error(env, db, "invalid UTF-8 SQL text");
                return SQLITE_ERROR;
            }
        }
    };

    let Some(database) = env.framework_state.sqlite.databases.get_mut(&db) else {
        return SQLITE_ERROR;
    };
    let Ok(prepared) = database.connection.prepare(&sql_text) else {
        set_last_error(env, db, "failed to prepare SQL");
        return SQLITE_ERROR;
    };

    let parameter_count = prepared.parameter_count();
    let columns = prepared
        .column_names()
        .iter()
        .map(|name| (*name).to_string())
        .collect();
    drop(prepared);

    let stmt = env.mem.alloc(1);
    env.mem.write(stmt_out, stmt);
    if !tail_out.is_null() {
        env.mem.write(tail_out, Ptr::null());
    }
    env.framework_state.sqlite.statements.insert(
        stmt,
        Statement {
            db,
            sql: sql_text,
            bindings: vec![CellValue::Null; parameter_count],
            columns,
            rows: Vec::new(),
            next_row: 0,
            current_row: None,
            executed: false,
            column_allocations: Vec::new(),
        },
    );
    SQLITE_OK
}

fn sqlite3_step(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    clear_column_allocations(env, stmt);

    let Some((db, sql, bindings, already_executed)) = env
        .framework_state
        .sqlite
        .statements
        .get(&stmt)
        .map(|statement| {
            (
                statement.db,
                statement.sql.clone(),
                statement.bindings.clone(),
                statement.executed,
            )
        })
    else {
        return SQLITE_ERROR;
    };

    if !already_executed {
        let outcome = {
            let Some(database) = env.framework_state.sqlite.databases.get_mut(&db) else {
                return SQLITE_ERROR;
            };
            let Ok(mut prepared) = database.connection.prepare(&sql) else {
                database.last_error = "failed to prepare SQL for execution".to_string();
                return SQLITE_ERROR;
            };
            let params = params_from_iter(bindings.iter().map(CellValue::to_sqlite_value));
            if prepared.column_count() == 0 {
                match prepared.execute(params) {
                    Ok(changes) => {
                        database.changes = changes as i32;
                        database.last_insert_rowid = database.connection.last_insert_rowid();
                        Ok(Vec::new())
                    }
                    Err(error) => Err(error.to_string()),
                }
            } else {
                let column_count = prepared.column_count();
                let mut rows = match prepared.query(params) {
                    Ok(rows) => rows,
                    Err(error) => {
                        return {
                            database.last_error = error.to_string();
                            SQLITE_ERROR
                        }
                    }
                };
                let mut result = Vec::new();
                loop {
                    match rows.next() {
                        Ok(Some(row)) => {
                            let mut values = Vec::with_capacity(column_count);
                            for column in 0..column_count {
                                let value = row
                                    .get_ref(column)
                                    .map(CellValue::from_value_ref)
                                    .unwrap_or(CellValue::Null);
                                values.push(value);
                            }
                            result.push(values);
                        }
                        Ok(None) => break Ok(result),
                        Err(error) => break Err(error.to_string()),
                    }
                }
            }
        };

        match outcome {
            Ok(rows) => {
                let Some(statement) = env.framework_state.sqlite.statements.get_mut(&stmt) else {
                    return SQLITE_ERROR;
                };
                statement.rows = rows;
                statement.next_row = 0;
                statement.current_row = None;
                statement.executed = true;
            }
            Err(error) => {
                set_last_error(env, db, error);
                return SQLITE_ERROR;
            }
        }
    }

    let Some(statement) = env.framework_state.sqlite.statements.get_mut(&stmt) else {
        return SQLITE_ERROR;
    };
    if let Some(row) = statement.rows.get(statement.next_row).cloned() {
        statement.next_row += 1;
        statement.current_row = Some(row);
        SQLITE_ROW
    } else {
        statement.current_row = None;
        SQLITE_DONE
    }
}

fn sqlite3_finalize(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    clear_column_allocations(env, stmt);
    if env
        .framework_state
        .sqlite
        .statements
        .remove(&stmt)
        .is_some()
    {
        env.mem.free(stmt);
    }
    SQLITE_OK
}

fn sqlite3_errmsg(env: &mut Environment, db: MutVoidPtr) -> ConstPtr<u8> {
    let message = env
        .framework_state
        .sqlite
        .databases
        .get(&db)
        .map(|database| database.last_error.as_str())
        .unwrap_or("invalid database handle");
    env.mem
        .alloc_and_write_cstr(message.as_bytes())
        .cast_const()
}

fn sqlite3_errcode(_env: &mut Environment, _db: MutVoidPtr) -> i32 {
    SQLITE_OK
}

fn sqlite3_bind_parameter_count(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    env.framework_state
        .sqlite
        .statements
        .get(&stmt)
        .map(|statement| statement.bindings.len() as i32)
        .unwrap_or_default()
}

fn sqlite3_bind_parameter_index(
    _env: &mut Environment,
    _stmt: MutVoidPtr,
    _name: ConstPtr<u8>,
) -> i32 {
    0
}

fn sqlite3_bind_parameter_name(
    env: &mut Environment,
    _stmt: MutVoidPtr,
    _index: i32,
) -> ConstPtr<u8> {
    env.mem.alloc_and_write_cstr(b"").cast_const()
}

fn bind_value(env: &mut Environment, stmt: MutVoidPtr, index: i32, value: CellValue) -> i32 {
    let Some(statement) = env.framework_state.sqlite.statements.get_mut(&stmt) else {
        return SQLITE_ERROR;
    };
    let Some(slot) = statement.bindings.get_mut(index.saturating_sub(1) as usize) else {
        return SQLITE_ERROR;
    };
    *slot = value;
    statement.executed = false;
    SQLITE_OK
}

fn sqlite3_bind_int(env: &mut Environment, stmt: MutVoidPtr, index: i32, value: i32) -> i32 {
    bind_value(env, stmt, index, CellValue::Integer(value as i64))
}

fn sqlite3_bind_int64(env: &mut Environment, stmt: MutVoidPtr, index: i32, value: i64) -> i32 {
    bind_value(env, stmt, index, CellValue::Integer(value))
}

fn sqlite3_bind_double(env: &mut Environment, stmt: MutVoidPtr, index: i32, value: f64) -> i32 {
    bind_value(env, stmt, index, CellValue::Float(value))
}

fn sqlite3_bind_null(env: &mut Environment, stmt: MutVoidPtr, index: i32) -> i32 {
    bind_value(env, stmt, index, CellValue::Null)
}

fn sqlite3_bind_blob(
    env: &mut Environment,
    stmt: MutVoidPtr,
    index: i32,
    value: ConstVoidPtr,
    bytes: i32,
    _destructor: ConstVoidPtr,
) -> i32 {
    let bytes = if value.is_null() || bytes <= 0 {
        Vec::new()
    } else {
        env.mem.bytes_at(value.cast(), bytes as u32).to_vec()
    };
    bind_value(env, stmt, index, CellValue::Blob(bytes))
}

fn sqlite3_bind_text(
    env: &mut Environment,
    stmt: MutVoidPtr,
    index: i32,
    value: ConstPtr<u8>,
    bytes: i32,
    _destructor: ConstVoidPtr,
) -> i32 {
    let value = if value.is_null() {
        String::new()
    } else if bytes < 0 {
        env.mem.cstr_at_utf8(value).unwrap_or_default().to_string()
    } else {
        String::from_utf8_lossy(env.mem.bytes_at(value, bytes as u32)).into_owned()
    };
    bind_value(env, stmt, index, CellValue::Text(value))
}

fn sqlite3_data_count(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    env.framework_state
        .sqlite
        .statements
        .get(&stmt)
        .and_then(|statement| statement.current_row.as_ref())
        .map(|row| row.len() as i32)
        .unwrap_or_default()
}

fn sqlite3_column_count(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    env.framework_state
        .sqlite
        .statements
        .get(&stmt)
        .map(|statement| statement.columns.len() as i32)
        .unwrap_or_default()
}

fn sqlite3_column_name(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> ConstPtr<u8> {
    let name = env
        .framework_state
        .sqlite
        .statements
        .get(&stmt)
        .and_then(|statement| statement.columns.get(column as usize))
        .cloned()
        .unwrap_or_default();
    env.mem.alloc_and_write_cstr(name.as_bytes()).cast_const()
}

fn sqlite3_column_type(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> i32 {
    current_cell(env, stmt, column)
        .map(|value| value.sqlite_type())
        .unwrap_or(SQLITE_NULL)
}

fn sqlite3_column_int(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> i32 {
    current_cell(env, stmt, column)
        .map(|value| value.as_i64() as i32)
        .unwrap_or_default()
}

fn sqlite3_column_int64(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> i64 {
    current_cell(env, stmt, column)
        .map(|value| value.as_i64())
        .unwrap_or_default()
}

fn sqlite3_column_double(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> f64 {
    current_cell(env, stmt, column)
        .map(|value| value.as_f64())
        .unwrap_or_default()
}

fn sqlite3_column_blob(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> ConstVoidPtr {
    let bytes = current_cell(env, stmt, column)
        .map(|value| value.as_blob_bytes())
        .unwrap_or_default();
    if bytes.is_empty() {
        Ptr::null()
    } else {
        alloc_stmt_buffer(env, stmt, &bytes)
            .cast_void()
            .cast_const()
    }
}

fn sqlite3_column_bytes(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> i32 {
    current_cell(env, stmt, column)
        .map(|value| value.as_blob_bytes().len() as i32)
        .unwrap_or_default()
}

fn sqlite3_column_text(env: &mut Environment, stmt: MutVoidPtr, column: i32) -> ConstPtr<u8> {
    let bytes = current_cell(env, stmt, column)
        .map(|value| value.as_text_bytes())
        .unwrap_or_default();
    alloc_stmt_buffer(env, stmt, &bytes).cast_const()
}

fn sqlite3_get_table(
    env: &mut Environment,
    db: MutVoidPtr,
    sql: ConstPtr<u8>,
    result_out: MutPtr<MutPtr<ConstPtr<u8>>>,
    rows_out: MutPtr<i32>,
    columns_out: MutPtr<i32>,
    error_out: MutPtr<ConstPtr<u8>>,
) -> i32 {
    let sql_text = if sql.is_null() {
        String::new()
    } else {
        match env.mem.cstr_at_utf8(sql) {
            Ok(sql) => sql.to_string(),
            Err(_) => {
                set_last_error(env, db, "invalid UTF-8 SQL text");
                return SQLITE_ERROR;
            }
        }
    };

    let query_result = {
        let Some(database) = env.framework_state.sqlite.databases.get_mut(&db) else {
            return SQLITE_ERROR;
        };
        let Ok(mut prepared) = database.connection.prepare(&sql_text) else {
            database.last_error = "failed to prepare SQL".to_string();
            return SQLITE_ERROR;
        };
        let column_names: Vec<String> = prepared
            .column_names()
            .iter()
            .map(|name| (*name).to_string())
            .collect();
        let column_count = column_names.len();
        let mut rows = match prepared.query([]) {
            Ok(rows) => rows,
            Err(error) => {
                database.last_error = error.to_string();
                return SQLITE_ERROR;
            }
        };
        let mut values = Vec::new();
        loop {
            match rows.next() {
                Ok(Some(row)) => {
                    let mut row_values = Vec::with_capacity(column_count);
                    for column in 0..column_count {
                        let value = row
                            .get_ref(column)
                            .map(CellValue::from_value_ref)
                            .unwrap_or(CellValue::Null);
                        row_values.push(value);
                    }
                    values.push(row_values);
                }
                Ok(None) => break (column_names, values),
                Err(error) => {
                    database.last_error = error.to_string();
                    return SQLITE_ERROR;
                }
            }
        }
    };

    let (column_names, rows) = query_result;
    let mut allocations = Vec::new();
    let mut pointers = Vec::new();
    for column in &column_names {
        let pointer = env.mem.alloc_and_write_cstr(column.as_bytes());
        allocations.push(pointer.cast());
        pointers.push(pointer.cast_const());
    }
    for row in &rows {
        for value in row {
            let pointer = env.mem.alloc_and_write_cstr(&value.as_text_bytes());
            allocations.push(pointer.cast());
            pointers.push(pointer.cast_const());
        }
    }

    let table_ptr = if pointers.is_empty() {
        Ptr::null()
    } else {
        let table_ptr: MutPtr<ConstPtr<u8>> = env
            .mem
            .alloc((pointers.len() as u32) * guest_size_of::<ConstPtr<u8>>())
            .cast();
        for (index, pointer) in pointers.iter().copied().enumerate() {
            env.mem.write(table_ptr + index as u32, pointer);
        }
        allocations.push(table_ptr.cast());
        table_ptr
    };
    if !result_out.is_null() {
        env.mem.write(result_out, table_ptr);
    }
    if !rows_out.is_null() {
        env.mem.write(rows_out, rows.len() as i32);
    }
    if !columns_out.is_null() {
        env.mem.write(columns_out, column_names.len() as i32);
    }
    if !error_out.is_null() {
        env.mem.write(error_out, Ptr::null());
    }
    if !table_ptr.is_null() {
        env.framework_state
            .sqlite
            .tables
            .insert(table_ptr, allocations);
    }
    SQLITE_OK
}

fn sqlite3_free_table(env: &mut Environment, result: MutPtr<ConstPtr<u8>>) {
    if let Some(allocations) = env.framework_state.sqlite.tables.remove(&result) {
        for allocation in allocations {
            env.mem.free(allocation);
        }
    }
}

fn sqlite3_free(env: &mut Environment, ptr: MutVoidPtr) {
    if !ptr.is_null() {
        env.mem.free(ptr);
    }
}

fn sqlite3_exec(
    env: &mut Environment,
    db: MutVoidPtr,
    sql: ConstPtr<u8>,
    _callback: ConstVoidPtr,
    _callback_arg: MutVoidPtr,
    error_out: MutPtr<ConstPtr<u8>>,
) -> i32 {
    let sql_text = if sql.is_null() {
        String::new()
    } else {
        match env.mem.cstr_at_utf8(sql) {
            Ok(sql) => sql.to_string(),
            Err(_) => {
                set_last_error(env, db, "invalid UTF-8 SQL text");
                return SQLITE_ERROR;
            }
        }
    };

    let result = env
        .framework_state
        .sqlite
        .databases
        .get_mut(&db)
        .ok_or_else(|| "invalid database handle".to_string())
        .and_then(|database| {
            database
                .connection
                .execute_batch(&sql_text)
                .map_err(|error| error.to_string())
                .map(|_| {
                    database.changes = database.connection.changes() as i32;
                    database.last_insert_rowid = database.connection.last_insert_rowid();
                })
        });

    match result {
        Ok(()) => {
            if !error_out.is_null() {
                env.mem.write(error_out, Ptr::null());
            }
            SQLITE_OK
        }
        Err(error) => {
            set_last_error(env, db, error.clone());
            if !error_out.is_null() {
                let ptr = env.mem.alloc_and_write_cstr(error.as_bytes()).cast_const();
                env.mem.write(error_out, ptr);
            }
            SQLITE_ERROR
        }
    }
}

fn sqlite3_reset(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    clear_column_allocations(env, stmt);
    let Some(statement) = env.framework_state.sqlite.statements.get_mut(&stmt) else {
        return SQLITE_ERROR;
    };
    statement.rows.clear();
    statement.next_row = 0;
    statement.current_row = None;
    statement.executed = false;
    SQLITE_OK
}

fn sqlite3_clear_bindings(env: &mut Environment, stmt: MutVoidPtr) -> i32 {
    let Some(statement) = env.framework_state.sqlite.statements.get_mut(&stmt) else {
        return SQLITE_ERROR;
    };
    statement.bindings.fill(CellValue::Null);
    statement.executed = false;
    SQLITE_OK
}

fn sqlite3_changes(env: &mut Environment, db: MutVoidPtr) -> i32 {
    env.framework_state
        .sqlite
        .databases
        .get(&db)
        .map(|database| database.changes)
        .unwrap_or_default()
}

fn sqlite3_last_insert_rowid(env: &mut Environment, db: MutVoidPtr) -> i64 {
    env.framework_state
        .sqlite
        .databases
        .get(&db)
        .map(|database| database.last_insert_rowid)
        .unwrap_or_default()
}

fn sqlite3_threadsafe(_env: &mut Environment) -> i32 {
    1
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(sqlite3_open(_, _)),
    export_c_func!(sqlite3_open_v2(_, _, _, _)),
    export_c_func!(sqlite3_close(_)),
    export_c_func!(sqlite3_prepare_v2(_, _, _, _, _)),
    export_c_func!(sqlite3_step(_)),
    export_c_func!(sqlite3_finalize(_)),
    export_c_func!(sqlite3_errmsg(_)),
    export_c_func!(sqlite3_errcode(_)),
    export_c_func!(sqlite3_bind_parameter_count(_)),
    export_c_func!(sqlite3_bind_parameter_index(_, _)),
    export_c_func!(sqlite3_bind_parameter_name(_, _)),
    export_c_func!(sqlite3_bind_int(_, _, _)),
    export_c_func!(sqlite3_bind_int64(_, _, _)),
    export_c_func!(sqlite3_bind_double(_, _, _)),
    export_c_func!(sqlite3_bind_null(_, _)),
    export_c_func!(sqlite3_bind_blob(_, _, _, _, _)),
    export_c_func!(sqlite3_bind_text(_, _, _, _, _)),
    export_c_func!(sqlite3_data_count(_)),
    export_c_func!(sqlite3_column_count(_)),
    export_c_func!(sqlite3_column_name(_, _)),
    export_c_func!(sqlite3_column_type(_, _)),
    export_c_func!(sqlite3_column_int(_, _)),
    export_c_func!(sqlite3_column_int64(_, _)),
    export_c_func!(sqlite3_column_double(_, _)),
    export_c_func!(sqlite3_column_blob(_, _)),
    export_c_func!(sqlite3_column_bytes(_, _)),
    export_c_func!(sqlite3_column_text(_, _)),
    export_c_func!(sqlite3_get_table(_, _, _, _, _, _)),
    export_c_func!(sqlite3_free_table(_)),
    export_c_func!(sqlite3_free(_)),
    export_c_func!(sqlite3_exec(_, _, _, _, _)),
    export_c_func!(sqlite3_reset(_)),
    export_c_func!(sqlite3_clear_bindings(_)),
    export_c_func!(sqlite3_changes(_)),
    export_c_func!(sqlite3_last_insert_rowid(_)),
    export_c_func!(sqlite3_threadsafe()),
];

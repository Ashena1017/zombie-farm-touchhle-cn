/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSURLConnection`.

use super::{ns_data, ns_string, NSInteger, NSUInteger};
use crate::environment::Environment;
use crate::mem::MutPtr;
use crate::objc::{
    autorelease, id, msg, msg_class, msg_send, nil, objc_classes, release, retain, ClassExports,
    HostObject, NSZonePtr,
};
use std::borrow::Cow;
use std::sync::OnceLock;
use std::time::Duration;

const NSURLErrorDomain: &str = "NSURLErrorDomain";
const ZFR_HTTP_BASE_URL_ENV: &str = "TOUCHHLE_ZOMBIE_FARM_HTTP_BASE_URL";
const ZFR_BUNDLE_ID: &str = "com.playforge.ZFR.LZ54D2GT3D";
const ZFR_BUNDLE_VERSION: &str = "1.0";
const MAX_RESPONSE_BYTES: usize = 8 << 20;
const ZFR_HTTP_GLOBAL_TIMEOUT: Duration = Duration::from_secs(6);
const ZFR_HTTP_PHASE_TIMEOUT: Duration = Duration::from_secs(3);
const ZFR_HTTP_BODY_TIMEOUT: Duration = Duration::from_secs(5);

/// Our helper type, Foundation just uses ints.
type NSURLErrorCode = NSInteger;
const NSURLErrorTimedOut: NSURLErrorCode = -1001;
const NSURLErrorCannotConnectToHost: NSURLErrorCode = -1004;
const NSURLErrorNotConnectedToInternet: NSURLErrorCode = -1009;
const NSURLErrorBadServerResponse: NSURLErrorCode = -1011;

struct NSURLConnectionHostObject {
    request: id,
    delegate: id,
    started: bool,
    cancelled: bool,
}
impl HostObject for NSURLConnectionHostObject {}

struct NSHTTPURLResponseHostObject {
    url: id,
    status_code: NSInteger,
    header_fields: id,
    expected_content_length: i64,
    mime_type: id,
}
impl HostObject for NSHTTPURLResponseHostObject {}

#[derive(Debug)]
pub(crate) struct ZombieFarmHttpResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSURLConnection: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::new(NSURLConnectionHostObject {
        request: nil,
        delegate: nil,
        started: false,
        cancelled: false,
    }), &mut env.mem)
}

+ (id)sendSynchronousRequest:(id)request // NSURLRequest *
           returningResponse:(MutPtr<id>)response // NSURLResponse **
                       error:(MutPtr<id>)out_error { // NSError **
    if !response.is_null() {
        env.mem.write(response, nil);
    }
    if !out_error.is_null() {
        env.mem.write(out_error, nil);
    }

    match perform_request(env, request) {
        Ok(host_response) => {
            let response_object = make_http_response(env, request, &host_response);
            let data = make_data(env, &host_response.body);
            if !response.is_null() {
                env.mem.write(response, response_object);
            }
            data
        }
        Err(error) => {
            log!("ZombieFarm HTTP request failed: {}", error.message);
            if !out_error.is_null() {
                let error = make_url_error(env, error.code);
                env.mem.write(out_error, error);
            }
            nil
        }
    }
}

+ (id)connectionWithRequest:(id)request // NSURLRequest *
                   delegate:(id)delegate {
    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithRequest:request delegate:delegate];
    autorelease(env, new)
}

- (id)initWithRequest:(id)request // NSURLRequest *
             delegate:(id)delegate {
    msg![env; this initWithRequest:request delegate:delegate startImmediately:true]
}

- (id)initWithRequest:(id)request // NSURLRequest *
             delegate:(id)delegate
     startImmediately:(bool)start_immediately {
    if request == nil {
        release(env, this);
        return nil;
    }
    let request = retain(env, request);
    let host = env.objc.borrow_mut::<NSURLConnectionHostObject>(this);
    host.request = request;
    host.delegate = delegate;

    if start_immediately {
        () = msg![env; this start];
    }
    this
}

- (())start {
    let (request, delegate, should_start) = {
        let host = env.objc.borrow_mut::<NSURLConnectionHostObject>(this);
        let should_start = !host.started && !host.cancelled;
        host.started = true;
        (host.request, host.delegate, should_start)
    };
    if !should_start {
        return;
    }

    match perform_request(env, request) {
        Ok(host_response) => {
            let response_object = make_http_response(env, request, &host_response);
            call_delegate_two_args(env, delegate, "connection:didReceiveResponse:", this, response_object);
            if !host_response.body.is_empty() {
                let data = make_data(env, &host_response.body);
                call_delegate_two_args(env, delegate, "connection:didReceiveData:", this, data);
            }
            call_delegate_one_arg(env, delegate, "connectionDidFinishLoading:", this);
        }
        Err(error) => {
            log!("ZombieFarm HTTP request failed: {}", error.message);
            let error = make_url_error(env, error.code);
            call_delegate_two_args(env, delegate, "connection:didFailWithError:", this, error);
        }
    }
}

- (())cancel {
    env.objc.borrow_mut::<NSURLConnectionHostObject>(this).cancelled = true;
}

- (())dealloc {
    let request = env.objc.borrow::<NSURLConnectionHostObject>(this).request;
    release(env, request);
    env.objc.dealloc_object(this, &mut env.mem);
}

@end

@implementation NSURLResponse: NSObject
@end

@implementation NSHTTPURLResponse: NSURLResponse

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::new(NSHTTPURLResponseHostObject {
        url: nil,
        status_code: 0,
        header_fields: nil,
        expected_content_length: -1,
        mime_type: nil,
    }), &mut env.mem)
}

- (NSInteger)statusCode {
    env.objc.borrow::<NSHTTPURLResponseHostObject>(this).status_code
}

- (id)URL {
    env.objc.borrow::<NSHTTPURLResponseHostObject>(this).url
}

- (id)allHeaderFields {
    env.objc.borrow::<NSHTTPURLResponseHostObject>(this).header_fields
}

- (i64)expectedContentLength {
    env.objc.borrow::<NSHTTPURLResponseHostObject>(this).expected_content_length
}

- (id)MIMEType {
    env.objc.borrow::<NSHTTPURLResponseHostObject>(this).mime_type
}

- (())dealloc {
    let host = env.objc.borrow::<NSHTTPURLResponseHostObject>(this);
    let url = host.url;
    let header_fields = host.header_fields;
    let mime_type = host.mime_type;
    release(env, url);
    release(env, header_fields);
    release(env, mime_type);
    env.objc.dealloc_object(this, &mut env.mem);
}

@end

};

#[derive(Debug)]
struct RequestError {
    code: NSURLErrorCode,
    message: String,
}

pub(super) fn zombie_farm_http_redirect_enabled(env: &Environment) -> bool {
    zombie_farm_http_base_url(env).is_some()
}

pub(crate) fn zombie_farm_http_base_url(env: &Environment) -> Option<String> {
    if env.bundle.bundle_identifier() != ZFR_BUNDLE_ID
        || env.bundle.bundle_version() != ZFR_BUNDLE_VERSION
    {
        return None;
    }
    let value = std::env::var(ZFR_HTTP_BASE_URL_ENV).ok()?;
    let Some(value) = normalize_zombie_farm_http_base_url(&value) else {
        static LOGGED: OnceLock<()> = OnceLock::new();
        if LOGGED.set(()).is_ok() {
            log!(
                "ZombieFarm HTTP redirect ignored: {} must be an http:// or https:// base URL without credentials",
                ZFR_HTTP_BASE_URL_ENV
            );
        }
        return None;
    };
    Some(value)
}

fn normalize_zombie_farm_http_base_url(value: &str) -> Option<String> {
    let value = value.trim().trim_end_matches('/');
    let uri: ureq::http::Uri = value.parse().ok()?;
    if !matches!(uri.scheme_str(), Some("http") | Some("https")) || uri.host().is_none() {
        return None;
    }
    if uri
        .authority()
        .is_some_and(|authority| authority.as_str().contains('@'))
    {
        return None;
    }
    Some(value.to_string())
}

pub(crate) fn zombie_farm_http_request(
    method: &str,
    url: &str,
    headers: &[(String, String)],
    body: Vec<u8>,
) -> Result<ZombieFarmHttpResponse, String> {
    let method: ureq::http::Method = method
        .parse()
        .map_err(|_| "unsupported HTTP method".to_string())?;
    let mut request_builder = ureq::http::Request::builder().method(method).uri(url);
    for (name, value) in headers {
        if is_forwarded_header(name) {
            request_builder = request_builder.header(name, value);
        }
    }
    let request = request_builder
        .body(body)
        .map_err(|_| "invalid HTTP request".to_string())?;

    static AGENT: OnceLock<ureq::Agent> = OnceLock::new();
    let agent = AGENT.get_or_init(|| zombie_farm_http_config().into());
    let mut response = agent.run(request).map_err(|error| error.to_string())?;
    let status = response.status().as_u16();
    let headers = response
        .headers()
        .iter()
        .filter_map(|(name, value)| {
            value
                .to_str()
                .ok()
                .map(|value| (name.as_str().to_string(), value.to_string()))
        })
        .collect();
    let body = response
        .body_mut()
        .with_config()
        .limit(MAX_RESPONSE_BYTES as u64)
        .read_to_vec()
        .map_err(|error| error.to_string())?;
    Ok(ZombieFarmHttpResponse {
        status,
        headers,
        body,
    })
}

fn zombie_farm_http_config() -> ureq::config::Config {
    ureq::Agent::config_builder()
        // NSURLConnection is currently synchronous in touchHLE. Keep both an
        // end-to-end deadline and phase deadlines so an unavailable HTTP/HTTPS
        // endpoint, DNS resolver, TLS handshake, upload, or response body
        // cannot leave the game waiting indefinitely.
        .timeout_global(Some(ZFR_HTTP_GLOBAL_TIMEOUT))
        .timeout_resolve(Some(ZFR_HTTP_PHASE_TIMEOUT))
        .timeout_connect(Some(ZFR_HTTP_PHASE_TIMEOUT))
        .timeout_send_request(Some(ZFR_HTTP_PHASE_TIMEOUT))
        .timeout_send_body(Some(ZFR_HTTP_BODY_TIMEOUT))
        .timeout_recv_response(Some(ZFR_HTTP_BODY_TIMEOUT))
        .timeout_recv_body(Some(ZFR_HTTP_BODY_TIMEOUT))
        .http_status_as_error(false)
        // The experimental base URL is an explicit user-selected endpoint.
        // Do not inherit HTTP_PROXY/HTTPS_PROXY, which can both leak the
        // public farm payload to an unrelated proxy and make local/private
        // endpoints hang unexpectedly.
        .proxy(None)
        .build()
}

fn perform_request(
    env: &mut Environment,
    request: id,
) -> Result<ZombieFarmHttpResponse, RequestError> {
    if request == nil {
        return Err(RequestError {
            code: NSURLErrorBadServerResponse,
            message: "request is nil".to_string(),
        });
    }
    let original_url = url_string_from_request(env, request).into_owned();
    let url = rewrite_zombie_farm_url(env, &original_url).ok_or_else(|| RequestError {
        code: NSURLErrorNotConnectedToInternet,
        message: "network is disabled for this URL".to_string(),
    })?;
    let method: id = msg![env; request HTTPMethod];
    let method = if method == nil {
        "GET".to_string()
    } else {
        ns_string::to_rust_string(env, method).into_owned()
    };
    let body: id = msg![env; request HTTPBody];
    let body = if body == nil {
        Vec::new()
    } else {
        ns_data::to_rust_slice(env, body).to_vec()
    };
    let headers = request_headers(env, request);
    if request_contains_password_field(&headers, &body) {
        return Err(RequestError {
            code: NSURLErrorBadServerResponse,
            message: "request contains a password-like field and was not sent".to_string(),
        });
    }

    let path = url
        .parse::<ureq::http::Uri>()
        .ok()
        .map(|uri| uri.path().to_string())
        .unwrap_or_else(|| "(invalid path)".to_string());
    log!("ZombieFarm HTTP: {} {}", method, path);
    let response = zombie_farm_http_request(&method, &url, &headers, body).map_err(|message| {
        let code = if message.to_ascii_lowercase().contains("timeout") {
            NSURLErrorTimedOut
        } else {
            NSURLErrorCannotConnectToHost
        };
        RequestError { code, message }
    })?;
    if !path.starts_with("/v1/") && response.status == 404 {
        return Err(RequestError {
            code: NSURLErrorCannotConnectToHost,
            message: "redirect server does not implement this legacy path".to_string(),
        });
    }
    Ok(response)
}

fn rewrite_zombie_farm_url(env: &Environment, original: &str) -> Option<String> {
    let base = zombie_farm_http_base_url(env)?;
    if original == base || original.starts_with(&(base.clone() + "/")) {
        return Some(original.to_string());
    }
    let original_uri: ureq::http::Uri = original.parse().ok()?;
    let host = original_uri.host()?.to_ascii_lowercase();
    if !matches!(host.as_str(), "api.zombiefarmgame.com" | "184.72.242.92") {
        return None;
    }
    let path_and_query = original_uri
        .path_and_query()
        .map(|value| value.as_str())
        .unwrap_or("/");
    Some(format!("{}{}", base, path_and_query))
}

fn request_headers(env: &mut Environment, request: id) -> Vec<(String, String)> {
    let dictionary: id = msg![env; request allHTTPHeaderFields];
    if dictionary == nil {
        return Vec::new();
    }
    let keys: id = msg![env; dictionary allKeys];
    let count: NSUInteger = msg![env; keys count];
    let mut headers = Vec::new();
    for index in 0..count {
        let key: id = msg![env; keys objectAtIndex:index];
        let value: id = msg![env; dictionary objectForKey:key];
        if key != nil && value != nil {
            headers.push((
                ns_string::to_rust_string(env, key).into_owned(),
                ns_string::to_rust_string(env, value).into_owned(),
            ));
        }
    }
    headers
}

fn is_forwarded_header(name: &str) -> bool {
    matches!(
        name.to_ascii_lowercase().as_str(),
        "accept" | "content-type" | "if-none-match" | "user-agent"
    )
}

fn request_contains_password_field(headers: &[(String, String)], body: &[u8]) -> bool {
    let content_type = headers
        .iter()
        .find(|(name, _)| name.eq_ignore_ascii_case("content-type"))
        .map(|(_, value)| value.to_ascii_lowercase())
        .unwrap_or_default();
    if !(content_type.contains("json")
        || content_type.contains("x-www-form-urlencoded")
        || content_type.contains("multipart/form-data"))
    {
        return false;
    }
    let body = String::from_utf8_lossy(body).to_ascii_lowercase();
    ["password=", "passwd=", "\"password\"", "name=\"password\""]
        .iter()
        .any(|needle| body.contains(needle))
}

fn make_data(env: &mut Environment, bytes: &[u8]) -> id {
    if bytes.is_empty() {
        let data: id = msg_class![env; NSData new];
        return autorelease(env, data);
    }
    let length: u32 = bytes.len().try_into().unwrap();
    let guest_bytes = env.mem.alloc(length);
    env.mem
        .bytes_at_mut(guest_bytes.cast(), length)
        .copy_from_slice(bytes);
    let data: id = msg_class![env; NSData dataWithBytes:(guest_bytes.cast_const()) length:length];
    env.mem.free(guest_bytes);
    data
}

fn make_http_response(env: &mut Environment, request: id, response: &ZombieFarmHttpResponse) -> id {
    let object: id = msg_class![env; NSHTTPURLResponse alloc];
    let url: id = msg![env; request URL];
    let header_fields: id = msg_class![env; NSMutableDictionary new];
    let mut mime_type = nil;
    for (name, value) in &response.headers {
        let name_object = ns_string::from_rust_string(env, name.clone());
        let value_object = ns_string::from_rust_string(env, value.clone());
        () = msg![env; header_fields setObject:value_object forKey:name_object];
        if name.eq_ignore_ascii_case("content-type") {
            let value = value.split(';').next().unwrap_or(value).trim().to_string();
            mime_type = ns_string::from_rust_string(env, value);
        }
    }
    let url = retain(env, url);
    let mime_type = retain(env, mime_type);
    let host = env.objc.borrow_mut::<NSHTTPURLResponseHostObject>(object);
    host.url = url;
    host.status_code = response.status.into();
    host.header_fields = header_fields;
    host.expected_content_length = response.body.len().try_into().unwrap();
    host.mime_type = mime_type;
    autorelease(env, object)
}

fn make_url_error(env: &mut Environment, code: NSURLErrorCode) -> id {
    let domain = ns_string::get_static_str(env, NSURLErrorDomain);
    let error = msg_class![env; NSError alloc];
    let error = msg![env; error initWithDomain:domain code:code userInfo:nil];
    autorelease(env, error)
}

fn call_delegate_one_arg(env: &mut Environment, delegate: id, selector_name: &str, arg: id) {
    if delegate == nil {
        return;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return;
    };
    if env.objc.object_has_method(&env.mem, delegate, selector) {
        let _: () = msg_send(env, (delegate, selector, arg));
    }
}

fn call_delegate_two_args(
    env: &mut Environment,
    delegate: id,
    selector_name: &str,
    first: id,
    second: id,
) {
    if delegate == nil {
        return;
    }
    let Some(selector) = env.objc.lookup_selector(selector_name) else {
        return;
    };
    if env.objc.object_has_method(&env.mem, delegate, selector) {
        let _: () = msg_send(env, (delegate, selector, first, second));
    }
}

fn url_string_from_request(env: &mut Environment, request: id) -> Cow<'static, str> {
    if request == nil {
        Cow::from("(null)")
    } else {
        let url = msg![env; request URL];
        let ns_string = msg![env; url absoluteString];
        ns_string::to_rust_string(env, ns_string)
    }
}

#[cfg(test)]
mod tests {
    use super::{
        normalize_zombie_farm_http_base_url, zombie_farm_http_config, ZFR_HTTP_BODY_TIMEOUT,
        ZFR_HTTP_GLOBAL_TIMEOUT, ZFR_HTTP_PHASE_TIMEOUT,
    };

    #[test]
    fn zombie_farm_base_url_accepts_http_and_https() {
        assert_eq!(
            normalize_zombie_farm_http_base_url(" http://127.0.0.1:28083/ "),
            Some("http://127.0.0.1:28083".to_string())
        );
        assert_eq!(
            normalize_zombie_farm_http_base_url("https://farm.example.com/"),
            Some("https://farm.example.com".to_string())
        );
    }

    #[test]
    fn zombie_farm_base_url_rejects_unsupported_or_credentialed_urls() {
        assert_eq!(
            normalize_zombie_farm_http_base_url("ftp://farm.example.com"),
            None
        );
        assert_eq!(
            normalize_zombie_farm_http_base_url("https://user:password@farm.example.com"),
            None
        );
        assert_eq!(
            normalize_zombie_farm_http_base_url("farm.example.com"),
            None
        );
    }

    #[test]
    fn zombie_farm_http_config_bounds_every_blocking_phase() {
        let timeouts = zombie_farm_http_config().timeouts();
        assert_eq!(timeouts.global, Some(ZFR_HTTP_GLOBAL_TIMEOUT));
        assert_eq!(timeouts.resolve, Some(ZFR_HTTP_PHASE_TIMEOUT));
        assert_eq!(timeouts.connect, Some(ZFR_HTTP_PHASE_TIMEOUT));
        assert_eq!(timeouts.send_request, Some(ZFR_HTTP_PHASE_TIMEOUT));
        assert_eq!(timeouts.send_body, Some(ZFR_HTTP_BODY_TIMEOUT));
        assert_eq!(timeouts.recv_response, Some(ZFR_HTTP_BODY_TIMEOUT));
        assert_eq!(timeouts.recv_body, Some(ZFR_HTTP_BODY_TIMEOUT));
    }
}

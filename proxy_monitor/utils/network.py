

def build_curl_args(proto, proxy_user, proxy_pwd, host, port, url, timeout, extra_flags=None):
    args = [
        "curl", "-x", f"{proto}://{host}:{port}",
        url,
        "--max-time", str(timeout),
        "-s", "-k",
        "--proxy-insecure" if proto == "https" else ""
    ]
    
    if proxy_user and proxy_pwd:
        args.extend(["-U", f"{proxy_user}:{proxy_pwd}"])
    
    if extra_flags:
        args.extend(extra_flags)
    
    return [a for a in args if a]

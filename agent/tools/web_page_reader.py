"""NeuroBridge web page reader (ported from notebook cell 138, previously notebook-only).

Extraction order: Tavily extract (TAVILY_API_KEY) -> direct HTTP fetch with BeautifulSoup.
URL safety: http/https only, no localhost / .local / private, loopback, link-local,
reserved or multicast addresses. For direct fetches the hostname is DNS-resolved and every
resolved address is checked, so a public name pointing at a private IP is refused.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

MAX_URLS = 3
MAX_CONTENT_CHARS = 8000


class UnsafeURLError(ValueError):
    pass


def _check_ip(ip):
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise UnsafeURLError("Private or reserved IP addresses are not allowed")


def validate_url(url, resolve_dns=False):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURLError("Only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL hostname is missing")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise UnsafeURLError("Local network URLs are not allowed")
    try:
        _check_ip(ipaddress.ip_address(host))
    except UnsafeURLError:
        raise
    except ValueError:
        pass  # a normal domain name
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UnsafeURLError(f"DNS resolution failed: {exc}")
        for info in infos:
            _check_ip(ipaddress.ip_address(info[4][0]))
    return url


def _tavily_extract(urls):
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    extraction = client.extract(urls=urls, extract_depth="advanced", format="markdown",
                                timeout=30)
    results = [{"url": i.get("url", ""), "content": i.get("raw_content") or i.get("content") or ""}
               for i in extraction.get("results", [])]
    failures = [{"url": i.get("url", ""), "error": i.get("error", "Extraction failed")}
                for i in extraction.get("failed_results", [])]
    return results, failures, "tavily_advanced"


def _direct_fetch(urls):
    import requests
    from bs4 import BeautifulSoup
    results, failures = [], []
    for url in urls:
        try:
            validate_url(url, resolve_dns=True)
            resp = requests.get(url, timeout=20, allow_redirects=False,
                                headers={"User-Agent": "NeuroBridge-Research/0.2"})
            if resp.is_redirect:
                target = resp.headers.get("Location", "")
                validate_url(target, resolve_dns=True)
                resp = requests.get(target, timeout=20, allow_redirects=False,
                                    headers={"User-Agent": "NeuroBridge-Research/0.2"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                tag.decompose()
            text = " ".join(soup.get_text(" ").split())
            results.append({"url": url, "content": text})
        except Exception as exc:
            failures.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return results, failures, "direct_http"


def web_page_reader(urls):
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        return {"success": False, "error": "urls must be a list or a single URL string",
                "results": [], "failed_results": []}
    urls = list(dict.fromkeys(u.strip() for u in urls if isinstance(u, str) and u.strip()))
    if not urls:
        return {"success": False, "error": "No valid URLs provided", "results": [],
                "failed_results": []}
    if len(urls) > MAX_URLS:
        return {"success": False, "error": f"Maximum {MAX_URLS} URLs allowed per call",
                "results": [], "failed_results": []}

    valid, rejected = [], []
    for url in urls:
        try:
            valid.append(validate_url(url))
        except UnsafeURLError as exc:
            rejected.append({"url": url, "error": str(exc)})
    if not valid:
        return {"success": False, "error": "All URLs were rejected during validation",
                "results": [], "failed_results": rejected}

    try:
        if os.environ.get("TAVILY_API_KEY"):
            raw, failures, method = _tavily_extract(valid)
        else:
            raw, failures, method = _direct_fetch(valid)
    except Exception as exc:
        return {"success": False, "results": [], "failed_results": rejected,
                "error": f"{type(exc).__name__}: {exc}"}

    processed = []
    for item in raw:
        content = item["content"] or ""
        processed.append({
            "url": item["url"],
            "success": bool(content.strip()),
            "content": content[:MAX_CONTENT_CHARS],
            "content_length": min(len(content), MAX_CONTENT_CHARS),
            "original_content_length": len(content),
            "truncated": len(content) > MAX_CONTENT_CHARS,
            "extraction_method": method,
        })
    extracted = sum(1 for p in processed if p["success"])
    return {
        "success": extracted > 0,
        "requested_urls": len(urls),
        "valid_urls": len(valid),
        "extracted_count": extracted,
        "results": processed,
        "failed_results": failures + rejected,
        "error": None if extracted else "No page content could be extracted",
    }

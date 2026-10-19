# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.28,<2"]
# ///
"""Read-only Crossref literature tools; no API key required."""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hleinweber-insight-literature")


def request(path, params=None):
    url = "https://api.crossref.org/works" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent":"hleinweber-insight-literature/0.1.0 (research homework)", "Accept":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)["message"]
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError("DOI not found in Crossref. Check spelling; NASA PDS/DataCite DOIs may not be indexed here.") from None
        if error.code == 429:
            raise ValueError("Crossref rate limit reached. Wait a minute and retry with fewer requests.") from None
        raise ValueError("Crossref returned an HTTP error. Retry later.") from None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        raise ValueError("Crossref lookup failed. Check your internet connection and try a shorter query.") from None


def summarize(work, include_abstract=False):
    date = work.get("published", work.get("issued", {})).get("date-parts", [[]])[0]
    authors = work.get("author", [])
    result = {
        "title": (work.get("title") or ["Untitled"])[0],
        "authors": [" ".join(filter(None,[a.get("given"),a.get("family")])) or a.get("name", "Unknown") for a in authors[:6]],
        "author_count":len(authors),
        "year":date[0] if date else None,
        "doi":work.get("DOI"),
        "url":"https://doi.org/"+work["DOI"] if work.get("DOI") else work.get("URL"),
        "venue":(work.get("container-title") or [""])[0],
        "type":work.get("type"),
    }
    if include_abstract:
        abstract = html.unescape(re.sub(r"<[^>]+>", " ", work.get("abstract", "")))
        abstract = " ".join(abstract.split())
        result["abstract_excerpt"] = abstract[:1200] or None
        result["abstract_truncated"] = len(abstract)>1200
        result["note"] = "Publisher-deposited metadata only; an abstract may be absent. This is not a full-paper review."
    return result


@mcp.tool()
def search_papers(query: str, limit: int = 5, from_year: int | None = None, to_year: int | None = None) -> dict:
    """Search Crossref scholarly metadata for the InSight Mars mission by keywords; e.g. 'InSight magnetic lander calibration'. Returns up to 10 titles, authors, years and DOI links ranked by Crossref relevance. Optional years are inclusive integers. Filters first 50 matches to mission terms; may miss papers without those terms in metadata. Inspect titles before citing. Does not search full text or cover all NASA reports."""
    query = query.strip()
    if not query or len(query)>500:
        raise ValueError("Use 1-500 characters of research keywords.")
    if not 1<=limit<=10:
        raise ValueError("limit must be between 1 and 10.")
    for year in [from_year,to_year]:
        if year is not None and not 1600<=year<=2100:
            raise ValueError("Years must be between 1600 and 2100.")
    if from_year is not None and to_year is not None and from_year>to_year:
        raise ValueError("from_year must not exceed to_year.")
    params={"query.title":query + " Mars", "rows":50}
    filters=[]
    if from_year is not None: filters.append(f"from-pub-date:{from_year}-01-01")
    if to_year is not None: filters.append(f"until-pub-date:{to_year}-12-31")
    if filters: params["filter"]=",".join(filters)
    data=request("",params)
    candidates = data.get("items",[])
    relevant=[]
    for work in candidates:
        text=" ".join(work.get("title",[]))+" "+work.get("abstract", "")
        if re.search(r"\binsight\b",text,re.I) and re.search(r"\bmars\b|\bmartian\b|\blander\b|\bfluxgate\b",text,re.I):
            if work.get("type") != "component":
                if re.search(r"magnet|fluxgate|\bifg\b",query,re.I) and not re.search(r"magnet|fluxgate|\bifg\b",text,re.I):
                    continue
                relevant.append(summarize(work))
    return {"query":query,"source":"Crossref","scope":"InSight mission: title or abstract must mention InSight and Mars, Martian, lander or fluxgate; scans first 50 Crossref matches.","results":relevant[:limit],"warning":"Keyword relevance is not evidence of a scientific claim; retrieve metadata and inspect the source."}


@mcp.tool()
def get_paper(doi: str) -> dict:
    """Retrieve a paper's Crossref metadata and an abstract excerpt when available. Input a DOI such as '10.1029/2020JE006505' or its https://doi.org/ URL. Returns source links; does not download full text. Use after search to verify a citation."""
    doi=re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    doi=re.sub(r"^doi:\s*", "", doi, flags=re.I)
    if not re.fullmatch(r"10\.\d{4,9}/[^\s]+",doi) or len(doi)>250:
        raise ValueError("Provide a DOI such as 10.1029/2020JE006505, not a paper title.")
    return summarize(request("/"+urllib.parse.quote(doi,safe="")),True)


@mcp.tool()
def insight_reference_sources() -> list[dict]:
    """List three curated primary-source starting points for InSight IFG interference/calibration research. These are fixed discovery links, not a live search or a complete bibliography. Read each source before making scientific claims; PDS and conference documents may be absent from Crossref."""
    return [
        {"title":"The Origin of Observed Magnetic Variability for a Sol on Mars From InSight", "url":"https://doi.org/10.1029/2020JE006505", "kind":"journal article"},
        {"title":"InSight Fluxgate Magnetometer Data Calibration Assessment and Implications", "url":"https://www.hou.usra.edu/meetings/lpsc2020/pdf/1331.pdf", "kind":"conference abstract, 2020"},
        {"title":"InSight IFG Data Calibration Description", "url":"https://pds.nasa.gov/ds-view/pds/viewDocument.jsp?identifier=urn%3Anasa%3Apds%3Ainsight-ifg-mars%3Adocument%3Ainsight-ifg-data-calibration-description&version=2.0", "kind":"NASA PDS calibration documentation"},
    ]

if __name__ == "__main__":
    mcp.run(transport="stdio")

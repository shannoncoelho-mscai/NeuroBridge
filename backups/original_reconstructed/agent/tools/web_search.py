
from ddgs import DDGS

def web_search(query: str, max_results: int = 8):
    results = []

    try:
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", "")
                })

        return {
            "success": True,
            "query": query,
            "count": len(results),
            "results": results,
            "error": None
        }

    except Exception as e:
        return {
            "success": False,
            "query": query,
            "count": 0,
            "results": [],
            "error": f"{type(e).__name__}: {str(e)}"
        }

def research_therapists(location="Panjim, Goa", age_group="children under 13"):
    queries = [
        f"child psychologist therapist {location} {age_group}",
        f"pediatric psychologist {location} child counselling",
        f"child mental health therapist {location}",
        f"psychologist children clinic {location}"
    ]

    collected = []

    for query in queries:
        result = web_search(query, max_results=5)
        collected.append(result)

    return {
        "success": any(r["success"] for r in collected),
        "location": location,
        "age_group": age_group,
        "research": collected
    }


"""NeuroBridge caregiver-approved appointment booking workflow."""

BOOKING_STATUSES = {
    "draft", "provider_found", "availability_checked",
    "awaiting_caregiver_approval", "booking_in_progress",
    "booking_requested", "confirmed", "failed", "cancelled"
}

def create_booking_request(
    provider_name=None,
    specialty=None,
    child_age=None,
    location=None,
    preferred_language=None,
    preferred_date=None,
    preferred_time=None,
    fee=None,
    notes=None,
):
    return {
        "provider_name": provider_name,
        "specialty": specialty,
        "child_age": child_age,
        "location": location,
        "preferred_language": preferred_language,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "fee": fee,
        "notes": notes,
        "availability_status": "not_checked",
        "booking_status": "draft",
        "caregiver_approved": False,
        "confirmation_reference": None,
    }

def record_availability(request, available_slots, source=None):
    request["available_slots"] = available_slots or []
    request["availability_source"] = source
    request["availability_status"] = (
        "available" if available_slots else "not_found"
    )
    if available_slots:
        request["booking_status"] = "availability_checked"
    return request

def request_caregiver_approval(request, slot=None):
    if request.get("availability_status") != "available":
        raise ValueError("Verified availability is required before approval.")
    if slot is not None:
        request["selected_slot"] = slot
    request["booking_status"] = "awaiting_caregiver_approval"
    request["caregiver_approved"] = False
    return request

def approve_booking(request, caregiver_approved=False):
    if request.get("booking_status") != "awaiting_caregiver_approval":
        raise ValueError("Booking is not awaiting approval.")
    if caregiver_approved is not True:
        raise PermissionError("Explicit caregiver approval is required.")
    request["caregiver_approved"] = True
    request["booking_status"] = "booking_in_progress"
    return request

def record_booking_result(request, success, confirmation_reference=None):
    if not request.get("caregiver_approved"):
        raise PermissionError("Cannot record booking without approval.")

    if success and confirmation_reference:
        request["booking_status"] = "confirmed"
        request["confirmation_reference"] = confirmation_reference
    elif success:
        request["booking_status"] = "booking_requested"
    else:
        request["booking_status"] = "failed"

    return request

def booking_summary(request):
    return {
        "provider": request.get("provider_name"),
        "specialty": request.get("specialty"),
        "location": request.get("location"),
        "selected_slot": request.get("selected_slot"),
        "fee": request.get("fee"),
        "status": request.get("booking_status"),
        "caregiver_approved": request.get("caregiver_approved", False),
        "confirmation_reference": request.get("confirmation_reference"),
    }

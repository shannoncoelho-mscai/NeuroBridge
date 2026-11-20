"""Default NeuroBridge tool registry.

Permission model
- Research tools (web_search, web_page_reader) and read-only registry lookups need no
  special permission.
- request_appointment / cancel_appointment are consequential: they require the
  'booking:write' permission AND explicit human approval for each call.
- approve_appointment (which reserves a slot) is deliberately NOT an agent tool. Only the
  caregiver can confirm a booking, through the API's /booking/approve endpoint.
"""
from agent.tools.registry import ToolRegistry, ToolSpec
from agent.tools.web_search import web_search as default_web_search
from agent.tools.web_page_reader import web_page_reader as default_page_reader

BOOKING_WRITE = "booking:write"


def build_tool_registry(booking_store=None, search_fn=None, reader_fn=None, event_store=None):
    registry = ToolRegistry()

    registry.register(ToolSpec(
        name="web_search",
        description="Search the web. Arguments: query (short, <= 12 words), max_results.",
        function=search_fn or default_web_search,
        required_arguments={"query"},
        metadata={"category": "research", "consequential": False},
    ))
    registry.register(ToolSpec(
        name="web_page_reader",
        description=("Read up to 3 web pages found by web_search. Argument: urls (list). "
                     "If urls is omitted the agent uses the top-ranked search results."),
        function=reader_fn or default_page_reader,
        required_arguments={"urls"},
        metadata={"category": "research", "consequential": False},
    ))

    if booking_store is not None:
        registry.register(ToolSpec(
            name="provider_search",
            description=("Search VERIFIED providers in the NeuroBridge registry. Arguments: "
                         "profession, specialty, language, location, child_age, online_only."),
            function=booking_store.search_providers,
            metadata={"category": "booking", "consequential": False},
        ))
        registry.register(ToolSpec(
            name="find_slots",
            description=("Find available slots of verified providers. Arguments: provider_id, "
                         "location, specialty, language, child_age."),
            function=booking_store.find_available_slots,
            metadata={"category": "booking", "consequential": False},
        ))
        registry.register(ToolSpec(
            name="request_appointment",
            description=("Create a PENDING appointment request (does not reserve the slot). "
                         "Arguments: slot_id, caregiver_user_id, child_age, caregiver_notes. "
                         "Requires caregiver approval."),
            function=booking_store.request_appointment,
            required_arguments={"slot_id", "caregiver_user_id"},
            required_permissions={BOOKING_WRITE},
            approval_required=True,
            metadata={"category": "booking", "consequential": True},
        ))
        registry.register(ToolSpec(
            name="cancel_appointment",
            description="Cancel an appointment. Arguments: appointment_id, caregiver_user_id.",
            function=booking_store.cancel_appointment,
            required_arguments={"appointment_id", "caregiver_user_id"},
            required_permissions={BOOKING_WRITE},
            approval_required=True,
            metadata={"category": "booking", "consequential": True},
        ))
    if event_store is not None:
        registry.register(ToolSpec(
            name="event_search",
            description=("Search NeuroBridge community events: support groups, workshops, social "
                         "gatherings, clubs, community meetings, activities. Arguments: event_type "
                         "(support_group|workshop|social_gathering|club|community_meeting|activity|"
                         "clinic_session), audience (e.g. autism, adhd, caregivers, psychosis, did), "
                         "text, location, online (true/false), accessibility (e.g. sensory_friendly)."),
            function=event_store.search_events,
            metadata={"category": "events", "consequential": False},
        ))

        def register_for_event(event_id, user_id, approved_details_hash, attendees=1, needs=None):
            # Reaching this function means the caregiver approved these exact details in the run.
            return event_store.register(event_id, user_id, attendees=attendees, needs=needs,
                                        approved_details_hash=approved_details_hash,
                                        explicit_approval=True)

        registry.register(ToolSpec(
            name="register_for_event",
            description=("Register the user for an event found with event_search. Arguments: event_id "
                         "(optional: defaults to the top search result), attendees, needs (accessibility "
                         "requests). Requires the user's approval of the exact details."),
            function=register_for_event,
            required_arguments={"event_id", "user_id", "approved_details_hash"},
            required_permissions={BOOKING_WRITE},
            approval_required=True,
            metadata={"category": "events", "consequential": True},
        ))
    return registry

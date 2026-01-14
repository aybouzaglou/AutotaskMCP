#!/usr/bin/env python3
"""
Autotask MCP Server v3

An MCP server that provides access to Autotask PSA platform for ticket management,
company and contact management, time entries, ticket notes, and more.

Key Features:
- Ticket CRUD operations
- TicketNotes creation (proper endpoint: /Tickets/{id}/Notes)
- TimeEntries creation (proper endpoint: /TimeEntries)
- Company and Contact search
- Resource lookup

Authentication: Uses username, secret, and API integration code in headers.
"""

import os
import json
import logging
import httpx
from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError

# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("autotask_mcp")

# Initialize MCP server
mcp = FastMCP("autotask", mask_error_details=True)

# =============================================================================
# CONFIGURATION
# =============================================================================

AUTOTASK_USERNAME = os.getenv("AUTOTASK_USERNAME", "")
AUTOTASK_SECRET = os.getenv("AUTOTASK_SECRET", "")
AUTOTASK_INTEGRATION_CODE = os.getenv("AUTOTASK_INTEGRATION_CODE", "")
AUTOTASK_API_URL = os.getenv("AUTOTASK_API_URL", "https://webservices14.autotask.net/ATServicesRest/v1.0")

API_TIMEOUT = 30.0
MAX_PAGE_SIZE = 500

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_headers() -> Dict[str, str]:
    """Get authentication headers for Autotask API requests."""
    return {
        "Content-Type": "application/json",
        "UserName": AUTOTASK_USERNAME,
        "Secret": AUTOTASK_SECRET,
        "ApiIntegrationcode": AUTOTASK_INTEGRATION_CODE,
    }


def _make_request(
    method: str,
    endpoint: str,
    data: Optional[Dict] = None,
    params: Optional[Dict] = None
) -> Dict[str, Any]:
    """Make an HTTP request to the Autotask API."""
    url = f"{AUTOTASK_API_URL}/{endpoint}"
    headers = _get_headers()
    
    logger.debug(f"API Request: {method} {url}")
    if data:
        logger.debug(f"Request body: {json.dumps(data, default=str)}")
    
    try:
        with httpx.Client(timeout=API_TIMEOUT) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = client.post(url, headers=headers, json=data)
            elif method.upper() == "PATCH":
                response = client.patch(url, headers=headers, json=data)
            elif method.upper() == "PUT":
                response = client.put(url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = client.delete(url, headers=headers)
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return {"error": f"Unsupported HTTP method: {method}"}
            
            logger.debug(f"API Response: {response.status_code}")
            
            # Log response for debugging
            if response.status_code >= 400:
                logger.error(f"API error {response.status_code}: {response.text[:500]}")
                return {
                    "error": f"API returned status {response.status_code}",
                    "status_code": response.status_code,
                    "response_text": response.text,
                    "url": url,
                    "method": method
                }
            
            if response.text:
                try:
                    result = response.json()
                    logger.debug(f"API success, items: {len(result.get('items', []))} item: {bool(result.get('item'))}")
                    return result
                except json.JSONDecodeError:
                    logger.error(f"JSON decode error: {response.text[:200]}")
                    return {"error": "Failed to parse API response", "raw_response": response.text}
            return {"success": True}
            
    except httpx.TimeoutException:
        logger.error(f"Request timed out: {url}")
        return {"error": "Request timed out"}
    except httpx.RequestError as e:
        logger.error(f"Request failed: {str(e)}")
        return {"error": f"Request failed: {str(e)}"}



def _query_entity(entity: str, filters: List[Dict], fields: Optional[List[str]] = None, max_records: int = 50) -> Dict[str, Any]:
    """
    Query an Autotask entity using the query endpoint.
    
    Args:
        entity: Entity name (e.g., "Tickets", "Companies", "Resources")
        filters: List of filter dictionaries with 'field', 'op', 'value'
        fields: Optional list of fields to return
        max_records: Maximum records to return (1-500, default 50)
    
    Returns:
        API response dictionary
    """
    # Autotask REST API query body structure per docs
    query_body: Dict[str, Any] = {
        "MaxRecords": max_records,
        "filter": filters,
    }
    if fields:
        query_body["IncludeFields"] = fields
    
    logger.debug(f"Query {entity}: filters={filters}, max_records={max_records}")
    return _make_request("POST", f"{entity}/query", data=query_body)


def _format_datetime_for_api(dt: Optional[datetime] = None) -> str:
    """Format datetime for Autotask API (ISO 8601 UTC)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_date_for_api(dt: Optional[datetime] = None) -> str:
    """Format date for Autotask API (YYYY-MM-DD)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


# =============================================================================
# INPUT MODELS
# =============================================================================

class SearchTicketsInput(BaseModel):
    """Input for searching tickets."""
    company_id: Optional[int] = Field(None, description="Filter by company ID")
    status: Optional[int] = Field(None, description="Filter by status ID")
    priority: Optional[int] = Field(None, description="Filter by priority ID")
    assigned_resource_id: Optional[int] = Field(None, description="Filter by assigned resource ID")
    queue_id: Optional[int] = Field(None, description="Filter by queue ID")
    title_contains: Optional[str] = Field(None, description="Filter by title containing this text")
    exclude_completed: Optional[bool] = Field(True, description="Exclude completed tickets (default: True)")
    max_results: Optional[int] = Field(50, description="Maximum number of results to return")


class CreateTicketInput(BaseModel):
    """Input for creating a ticket."""
    title: str = Field(..., description="Ticket title/subject")
    description: Optional[str] = Field(None, description="Ticket description")
    company_id: int = Field(..., description="Company ID for the ticket")
    status: Optional[int] = Field(1, description="Status ID (default: 1 = New)")
    priority: Optional[int] = Field(2, description="Priority ID (default: 2 = Medium)")
    queue_id: Optional[int] = Field(None, description="Queue ID to assign the ticket to")
    assigned_resource_id: Optional[int] = Field(None, description="Resource ID to assign the ticket to")
    assigned_resource_role_id: Optional[int] = Field(None, description="Role ID for the assigned resource")
    due_date_time: Optional[str] = Field(None, description="Due date/time in ISO format")
    ticket_type: Optional[int] = Field(1, description="Ticket type (1=Service Request, 2=Incident, etc.)")


class UpdateTicketInput(BaseModel):
    """Input for updating a ticket."""
    ticket_id: int = Field(..., description="The ticket ID to update")
    title: Optional[str] = Field(None, description="New ticket title")
    description: Optional[str] = Field(None, description="New ticket description")
    status: Optional[int] = Field(None, description="New status ID")
    priority: Optional[int] = Field(None, description="New priority ID")
    queue_id: Optional[int] = Field(None, description="New queue ID")
    assigned_resource_id: Optional[int] = Field(None, description="New assigned resource ID")
    assigned_resource_role_id: Optional[int] = Field(None, description="New role ID for assigned resource")
    due_date_time: Optional[str] = Field(None, description="New due date/time in ISO format")


class CreateTicketNoteInput(BaseModel):
    """
    Input for creating a ticket note.
    
    Required by Autotask API:
    - ticketId: The ticket to add the note to
    - description: The note content
    - noteType: Type of note (picklist - get values from your Autotask instance)
    - publish: Visibility setting (1=All Autotask Users, 2=Internal Only, etc.)
    """
    ticket_id: int = Field(..., description="The ticket ID to add the note to")
    title: Optional[str] = Field("", description="Note title (may be required depending on ticket category settings)")
    description: str = Field(..., description="The note content/body")
    note_type: int = Field(1, description="Note type ID (1=Task Detail, 2=Resolution, 3=Summary, etc. - varies by instance)")
    publish: int = Field(1, description="Publish/visibility (1=All Autotask Users, 2=Internal Only, 3=Datto Internal)")


class CreateTimeEntryInput(BaseModel):
    """
    Input for creating a time entry.
    
    Required by Autotask API:
    - ticketId OR taskId: What the time is logged against
    - resourceId: The resource who did the work
    - roleId: The role for the resource (must be valid for the resource)
    - dateWorked: The date the work was performed
    - hoursWorked: Hours worked (> 0 and <= 24)
    - summaryNotes: Required for ticket time entries
    
    Optional but commonly used:
    - billingCodeId: Work type (General) allocation code
    - contractId: Contract to bill against
    - startDateTime/endDateTime: Start and end times
    - internalNotes: Internal notes (not visible to customers)
    - hoursToBill: Billable hours (if different from hoursWorked)
    - isNonBillable: Whether the time is non-billable
    - showOnInvoice: Whether to show on invoice
    """
    ticket_id: Optional[int] = Field(None, description="Ticket ID to log time against (required if no task_id)")
    task_id: Optional[int] = Field(None, description="Task ID to log time against (required if no ticket_id)")
    resource_id: int = Field(..., description="Resource ID who performed the work")
    role_id: int = Field(..., description="Role ID for the resource (must be valid for the resource)")
    date_worked: Optional[str] = Field(None, description="Date worked in YYYY-MM-DD format (defaults to today)")
    hours_worked: float = Field(..., description="Hours worked (must be > 0 and <= 24)")
    summary_notes: str = Field(..., description="Summary/description of work performed (required for ticket time entries)")
    internal_notes: Optional[str] = Field(None, description="Internal notes (not visible to customers)")
    billing_code_id: Optional[int] = Field(None, description="Work Type/Billing Code ID")
    contract_id: Optional[int] = Field(None, description="Contract ID to bill against")
    hours_to_bill: Optional[float] = Field(None, description="Billable hours (defaults to hours_worked)")
    is_non_billable: Optional[bool] = Field(None, description="Whether the time is non-billable")
    show_on_invoice: Optional[bool] = Field(None, description="Whether to show on invoice")
    start_date_time: Optional[str] = Field(None, description="Start time in ISO format")
    end_date_time: Optional[str] = Field(None, description="End time in ISO format")


class SearchCompaniesInput(BaseModel):
    """Input for searching companies."""
    name_contains: Optional[str] = Field(None, description="Filter by company name containing this text")
    is_active: Optional[bool] = Field(True, description="Filter by active status")
    max_results: Optional[int] = Field(50, description="Maximum number of results")


class SearchContactsInput(BaseModel):
    """Input for searching contacts."""
    company_id: Optional[int] = Field(None, description="Filter by company ID")
    email_contains: Optional[str] = Field(None, description="Filter by email containing this text")
    first_name: Optional[str] = Field(None, description="Filter by first name")
    last_name: Optional[str] = Field(None, description="Filter by last name")
    is_active: Optional[bool] = Field(True, description="Filter by active status (default: True)")
    max_results: Optional[int] = Field(50, description="Maximum number of results")


class SearchResourcesInput(BaseModel):
    """Input for searching resources (users/technicians)."""
    first_name: Optional[str] = Field(None, description="Filter by first name")
    last_name: Optional[str] = Field(None, description="Filter by last name")
    email: Optional[str] = Field(None, description="Filter by email")
    is_active: Optional[bool] = Field(True, description="Filter by active status")
    max_results: Optional[int] = Field(50, description="Maximum number of results")


# =============================================================================
# TOOLS - TICKETS
# =============================================================================

@mcp.tool
async def autotask_get_ticket(
    ticket_id: Annotated[int, Field(description="The ticket ID to retrieve")],
    ctx: Context | None = None,
) -> dict:
    """Get a ticket by ID from Autotask."""
    result = _make_request("GET", f"Tickets/{ticket_id}")
    
    if "error" in result:
        if ctx:
            await ctx.error(
                f"get_ticket failed: {result['error']}",
                extra={"status_code": result.get("status_code"), "response_text": result.get("response_text")},
            )
        raise ToolError(f"Failed to get ticket {ticket_id}: {result['error']}")
    
    return result.get("item", result)


@mcp.tool
async def autotask_search_tickets(params: SearchTicketsInput, ctx: Context | None = None) -> dict:
    """Search for tickets in Autotask with various filters."""
    filters = []
    
    if params.company_id:
        filters.append({"op": "eq", "field": "companyID", "value": params.company_id})
    if params.status:
        filters.append({"op": "eq", "field": "status", "value": params.status})
    if params.priority:
        filters.append({"op": "eq", "field": "priority", "value": params.priority})
    if params.assigned_resource_id:
        filters.append({"op": "eq", "field": "assignedResourceID", "value": params.assigned_resource_id})
    if params.queue_id:
        filters.append({"op": "eq", "field": "queueID", "value": params.queue_id})
    if params.title_contains:
        filters.append({"op": "contains", "field": "title", "value": params.title_contains})
    
    # Exclude completed tickets by default (status 5 is typically Complete)
    if params.exclude_completed:
        filters.append({"op": "notequal", "field": "status", "value": 5})
    
    if not filters:
        # Default: get recent tickets
        filters.append({"op": "exist", "field": "id"})
    
    result = _query_entity("Tickets", filters)
    
    if "error" in result:
        if ctx:
            await ctx.error(
                f"search_tickets failed: {result['error']}",
                extra={"status_code": result.get("status_code"), "response_text": result.get("response_text"), "filters": filters},
            )
        raise ToolError(f"Failed to search tickets: {result['error']}")
    
    items = result.get("items", [])
    if params.max_results:
        items = items[:params.max_results]
    
    return {"count": len(items), "tickets": items}


@mcp.tool
async def autotask_create_ticket(params: CreateTicketInput) -> dict:
    """Create a new ticket in Autotask."""
    ticket_data = {
        "title": params.title,
        "companyID": params.company_id,
        "status": params.status,
        "priority": params.priority,
        "ticketType": params.ticket_type,
    }
    
    if params.description:
        ticket_data["description"] = params.description
    if params.queue_id:
        ticket_data["queueID"] = params.queue_id
    if params.assigned_resource_id:
        ticket_data["assignedResourceID"] = params.assigned_resource_id
    if params.assigned_resource_role_id:
        ticket_data["assignedResourceRoleID"] = params.assigned_resource_role_id
    if params.due_date_time:
        ticket_data["dueDateTime"] = params.due_date_time
    
    result = _make_request("POST", "Tickets", data=ticket_data)
    
    if "error" in result:
        raise ToolError(f"Failed to create ticket: {result['error']}")
    
    item = result.get("item", result)
    return {"success": True, "ticket_id": item.get("id"), "ticket": item}


@mcp.tool
async def autotask_update_ticket(params: UpdateTicketInput) -> dict:
    """
    Update an existing ticket in Autotask.
    
    Uses PATCH method to update only specified fields.
    Common status values: 1=New, 5=In Progress, 8=Waiting Customer, 5=Complete
    (Note: Status IDs vary by Autotask instance - use autotask_get_picklist_values to get exact values)
    """
    # First, get the current ticket to include required fields
    current = _make_request("GET", f"Tickets/{params.ticket_id}")
    if "error" in current:
        raise ToolError(f"Failed to fetch ticket {params.ticket_id}: {current['error']}")
    
    ticket = current.get("item", current)
    
    # Build update payload - must include id
    update_data: Dict[str, Any] = {"id": params.ticket_id}
    
    if params.title is not None:
        update_data["title"] = params.title
    if params.description is not None:
        update_data["description"] = params.description
    if params.status is not None:
        update_data["status"] = params.status
    if params.priority is not None:
        update_data["priority"] = params.priority
    if params.queue_id is not None:
        update_data["queueID"] = params.queue_id
    if params.assigned_resource_id is not None:
        update_data["assignedResourceID"] = params.assigned_resource_id
    if params.assigned_resource_role_id is not None:
        update_data["assignedResourceRoleID"] = params.assigned_resource_role_id
    if params.due_date_time is not None:
        update_data["dueDateTime"] = params.due_date_time
    
    result = _make_request("PATCH", "Tickets", data=update_data)
    
    if "error" in result:
        raise ToolError(f"Failed to update ticket {params.ticket_id}: {result['error']}")
    
    item = result.get("item", result)
    return {"success": True, "ticket_id": params.ticket_id, "updated_fields": update_data, "ticket": item}


# =============================================================================
# TOOLS - TICKET NOTES
# =============================================================================

@mcp.tool
async def autotask_create_ticket_note(params: CreateTicketNoteInput) -> dict:
    """
    Create a note on a ticket in Autotask.
    
    Uses the /Tickets/{id}/Notes endpoint (parent-child pattern).
    
    Required fields:
    - ticketId: The ticket to add the note to
    - description: The note content
    - noteType: Type of note (picklist value)
    - publish: Visibility setting
    
    Common noteType values (vary by instance):
    - 1 = Ticket Detail / Task Detail
    - 2 = Resolution
    - 3 = Summary
    - 13 = System Workflow Note
    
    Common publish values:
    - 1 = All Autotask Users
    - 2 = Internal Only
    - 3 = Datto Internal
    
    Use autotask_get_picklist_values to get exact values for your instance.
    """
    note_data = {
        "description": params.description,
        "noteType": params.note_type,
        "publish": params.publish,
    }
    
    if params.title:
        note_data["title"] = params.title
    
    result = _make_request("POST", f"Tickets/{params.ticket_id}/Notes", data=note_data)
    
    if "error" in result:
        raise ToolError(f"Failed to create ticket note: {result['error']}")
    
    item = result.get("item", result)
    return {"success": True, "note_id": item.get("id"), "ticket_id": params.ticket_id, "note": item}


# =============================================================================
# TOOLS - TIME ENTRIES
# =============================================================================

@mcp.tool
async def autotask_create_time_entry(params: CreateTimeEntryInput) -> dict:
    """
    Create a time entry in Autotask.
    
    Uses the /TimeEntries endpoint.
    
    IMPORTANT REQUIREMENTS:
    1. Must have either ticketId OR taskId (not both, not neither)
    2. resourceId must be a valid, active resource
    3. roleId must be a valid role for the resource
    4. hoursWorked must be > 0 and <= 24
    5. summaryNotes is required for ticket time entries
    6. dateWorked defaults to today if not provided
    
    The API stores all times in UTC.
    
    Common issues:
    - 500 error often means missing/invalid required field
    - Role must be associated with the resource
    - Contract must be active and associated with the ticket's company
    """
    if not params.ticket_id and not params.task_id:
        raise ToolError("Either ticket_id or task_id is required")
    
    if params.ticket_id and params.task_id:
        raise ToolError("Provide either ticket_id OR task_id, not both")
    
    if params.hours_worked <= 0 or params.hours_worked > 24:
        raise ToolError("hours_worked must be > 0 and <= 24")
    
    # Build the time entry data
    time_entry_data = {
        "resourceID": params.resource_id,
        "roleID": params.role_id,
        "hoursWorked": params.hours_worked,
        "summaryNotes": params.summary_notes,
        "dateWorked": params.date_worked or _format_date_for_api(),
    }
    
    # Add ticket or task ID
    if params.ticket_id:
        time_entry_data["ticketID"] = params.ticket_id
    else:
        time_entry_data["taskID"] = params.task_id
    
    # Add optional fields
    if params.internal_notes:
        time_entry_data["internalNotes"] = params.internal_notes
    if params.billing_code_id:
        time_entry_data["billingCodeID"] = params.billing_code_id
    if params.contract_id:
        time_entry_data["contractID"] = params.contract_id
    if params.hours_to_bill is not None:
        time_entry_data["hoursToBill"] = params.hours_to_bill
    if params.is_non_billable is not None:
        time_entry_data["isNonBillable"] = params.is_non_billable
    if params.show_on_invoice is not None:
        time_entry_data["showOnInvoice"] = params.show_on_invoice
    if params.start_date_time:
        time_entry_data["startDateTime"] = params.start_date_time
    if params.end_date_time:
        time_entry_data["endDateTime"] = params.end_date_time
    
    result = _make_request("POST", "TimeEntries", data=time_entry_data)
    
    if "error" in result:
        raise ToolError(f"Failed to create time entry: {result['error']}")
    
    item = result.get("item", result)
    return {
        "success": True,
        "time_entry_id": item.get("id"),
        "hours": params.hours_worked,
        "ticket_or_task_id": params.ticket_id or params.task_id,
        "time_entry": item
    }


# =============================================================================
# TOOLS - COMPANIES
# =============================================================================

@mcp.tool
async def autotask_search_companies(params: SearchCompaniesInput, ctx: Context | None = None) -> dict:
    """Search for companies in Autotask."""
    filters = []
    
    if params.name_contains:
        filters.append({"op": "contains", "field": "companyName", "value": params.name_contains})
    
    # Always apply active status filter (defaults to True)
    if params.is_active is not None:
        filters.append({"op": "eq", "field": "isActive", "value": params.is_active})
    
    if not filters:
        # If no filters at all, still filter by active
        filters.append({"op": "eq", "field": "isActive", "value": True})
    
    result = _query_entity("Companies", filters)
    
    if "error" in result:
        if ctx:
            await ctx.error(
                f"search_companies failed: {result['error']}",
                extra={"status_code": result.get("status_code"), "response_text": result.get("response_text"), "filters": filters},
            )
        raise ToolError(f"Failed to search companies: {result['error']}")
    
    items = result.get("items", [])
    if params.max_results:
        items = items[:params.max_results]
    
    return {"count": len(items), "companies": items}


@mcp.tool
async def autotask_get_company(
    company_id: Annotated[int, Field(description="The company ID to retrieve")]
) -> dict:
    """Get a company by ID from Autotask."""
    result = _make_request("GET", f"Companies/{company_id}")
    
    if "error" in result:
        raise ToolError(f"Failed to get company {company_id}: {result['error']}")
    
    return result.get("item", result)


# =============================================================================
# TOOLS - CONTACTS
# =============================================================================

@mcp.tool
async def autotask_search_contacts(params: SearchContactsInput) -> dict:
    """Search for contacts in Autotask."""
    filters = []
    
    if params.company_id:
        filters.append({"op": "eq", "field": "companyID", "value": params.company_id})
    if params.email_contains:
        filters.append({"op": "contains", "field": "emailAddress", "value": params.email_contains})
    if params.first_name:
        filters.append({"op": "contains", "field": "firstName", "value": params.first_name})
    if params.last_name:
        filters.append({"op": "contains", "field": "lastName", "value": params.last_name})
    
    # Always apply active status filter (defaults to True)
    if params.is_active is not None:
        filters.append({"op": "eq", "field": "isActive", "value": params.is_active})
    
    if not filters:
        # If no filters at all, still filter by active
        filters.append({"op": "eq", "field": "isActive", "value": True})
    
    result = _query_entity("Contacts", filters)
    
    if "error" in result:
        raise ToolError(f"Failed to search contacts: {result['error']}")
    
    items = result.get("items", [])
    if params.max_results:
        items = items[:params.max_results]
    
    return {"count": len(items), "contacts": items}


# =============================================================================
# TOOLS - RESOURCES
# =============================================================================

@mcp.tool
async def autotask_search_resources(params: SearchResourcesInput) -> dict:
    """Search for resources (users/technicians) in Autotask."""
    filters = []
    
    if params.first_name:
        filters.append({"op": "contains", "field": "firstName", "value": params.first_name})
    if params.last_name:
        filters.append({"op": "contains", "field": "lastName", "value": params.last_name})
    if params.email:
        filters.append({"op": "contains", "field": "email", "value": params.email})
    if params.is_active is not None:
        filters.append({"op": "eq", "field": "isActive", "value": params.is_active})
    
    if not filters:
        filters.append({"op": "exist", "field": "id"})
    
    result = _query_entity("Resources", filters)
    
    if "error" in result:
        raise ToolError(f"Failed to search resources: {result['error']}")
    
    items = result.get("items", [])
    if params.max_results:
        items = items[:params.max_results]
    
    return {"count": len(items), "resources": items}


@mcp.tool
async def autotask_get_resource(
    resource_id: Annotated[int, Field(description="The resource ID to retrieve")]
) -> dict:
    """Get a resource by ID from Autotask."""
    result = _make_request("GET", f"Resources/{resource_id}")
    
    if "error" in result:
        raise ToolError(f"Failed to get resource {resource_id}: {result['error']}")
    
    return result.get("item", result)


# =============================================================================
# TOOLS - PICKLIST VALUES
# =============================================================================

@mcp.tool
async def autotask_get_picklist_values(
    entity: Annotated[str, Field(description="Entity name (e.g., 'Tickets', 'TicketNotes', 'TimeEntries')")],
    field: Annotated[str, Field(description="Field name (e.g., 'status', 'priority', 'noteType', 'publish')")]
) -> dict:
    """
    Get picklist values for a field in Autotask.
    
    Use this to discover valid values for fields like:
    - Tickets/status
    - Tickets/priority
    - Tickets/ticketType
    - Tickets/queueID
    - TicketNotes/noteType
    - TicketNotes/publish
    - TimeEntries/type
    
    Example: entity="Tickets", field="status"
    """
    result = _make_request("GET", f"{entity}/entityInformation/fields")
    
    if "error" in result:
        raise ToolError(f"Failed to get picklist values for {entity}/{field}: {result['error']}")
    
    fields = result.get("fields", [])
    
    # Find the specific field
    target_field = None
    for f in fields:
        if f.get("name", "").lower() == field.lower():
            target_field = f
            break
    
    if not target_field:
        available_fields = [f.get("name") for f in fields if f.get("isPickList")]
        raise ToolError(f"Field '{field}' not found in {entity}. Available picklist fields: {available_fields}")
    
    if not target_field.get("isPickList"):
        raise ToolError(f"Field '{field}' is not a picklist field.")
    
    picklist_values = target_field.get("picklistValues", [])
    return {"entity": entity, "field": field, "values": picklist_values}


# =============================================================================
# TOOLS - ROLES (needed for time entries)
# =============================================================================

@mcp.tool
async def autotask_search_roles(
    is_active: Annotated[Optional[bool], Field(default=True, description="Filter by active status")] = True,
    max_results: Annotated[Optional[int], Field(default=50, description="Maximum number of results")] = 50
) -> dict:
    """
    Search for roles in Autotask.
    
    Roles are required when creating time entries.
    The role must be valid for the resource creating the time entry.
    """
    filters = []
    
    if is_active is not None:
        filters.append({"op": "eq", "field": "isActive", "value": is_active})
    
    if not filters:
        filters.append({"op": "exist", "field": "id"})
    
    result = _query_entity("Roles", filters)
    
    if "error" in result:
        raise ToolError(f"Failed to search roles: {result['error']}")
    
    items = result.get("items", [])
    if max_results:
        items = items[:max_results]
    
    return {"count": len(items), "roles": items}


# =============================================================================
# TOOLS - CONTRACTS
# =============================================================================

class SearchContractsInput(BaseModel):
    """Input for searching contracts."""
    company_id: Optional[int] = Field(None, description="Filter by company ID")
    contract_name: Optional[str] = Field(None, description="Filter by contract name")
    is_active: Optional[bool] = Field(True, description="Filter by active status")
    max_results: Optional[int] = Field(50, description="Maximum number of results")


@mcp.tool
async def autotask_search_contracts(params: SearchContractsInput) -> dict:
    """
    Search for contracts in Autotask.
    
    Useful for finding the correct contract_id for time entries.
    """
    filters = []
    
    if params.company_id:
        filters.append({"op": "eq", "field": "companyID", "value": params.company_id})
    if params.contract_name:
        filters.append({"op": "contains", "field": "contractName", "value": params.contract_name})
    if params.is_active is not None:
        filters.append({"op": "eq", "field": "isActive", "value": params.is_active})
    
    if not filters:
        filters.append({"op": "exist", "field": "id"})
    
    result = _query_entity("Contracts", filters)
    
    if "error" in result:
        raise ToolError(f"Failed to search contracts: {result['error']}")
    
    items = result.get("items", [])
    if params.max_results:
        items = items[:params.max_results]
    
    return {"count": len(items), "contracts": items}


# =============================================================================
# TOOLS - BILLING CODES (Work Types)
# =============================================================================

class SearchBillingCodesInput(BaseModel):
    """Input for searching billing codes (Work Types)."""
    name: Optional[str] = Field(None, description="Filter by billing code name")
    is_active: Optional[bool] = Field(True, description="Filter by active status")
    max_results: Optional[int] = Field(50, description="Maximum number of results")


@mcp.tool
async def autotask_search_billing_codes(params: SearchBillingCodesInput) -> dict:
    """
    Search for billing codes (Work Types) in Autotask.
    
    Useful for finding the correct billing_code_id for time entries.
    """
    filters = []
    
    if params.name:
        filters.append({"op": "contains", "field": "name", "value": params.name})
    if params.is_active is not None:
        filters.append({"op": "eq", "field": "isActive", "value": params.is_active})
    
    if not filters:
        filters.append({"op": "exist", "field": "id"})
    
    result = _query_entity("BillingCodes", filters)
    
    if "error" in result:
        raise ToolError(f"Failed to search billing codes: {result['error']}")
    
    items = result.get("items", [])
    if params.max_results:
        items = items[:params.max_results]
    
    return {"count": len(items), "billing_codes": items}


# =============================================================================
# RESOURCES
# =============================================================================

@mcp.resource("autotask://picklist/{entity}/{field}")
async def get_picklist_resource(entity: str, field: str) -> str:
    """
    Get picklist values for a specific entity and field.
    Example: autotask://picklist/Tickets/status
    """
    # Reuse the logic from the tool, but return a formatted string
    result = _make_request("GET", f"{entity}/entityInformation/fields")
    
    if "error" in result:
        return f"Error fetching picklist: {result['error']}"
    
    fields_data = result.get("fields", [])
    target_field = next((f for f in fields_data if f.get("name", "").lower() == field.lower()), None)
    
    if not target_field:
        return f"Field '{field}' not found in {entity}."
    
    if not target_field.get("isPickList"):
        return f"Field '{field}' is not a picklist field."
    
    values = target_field.get("picklistValues", [])
    
    # Format as a readable list
    lines = [f"# Picklist Values for {entity}.{field}"]
    for val in values:
        label = val.get("label", "Unknown")
        val_id = val.get("value", "Unknown")
        is_default = " (Default)" if val.get("isDefaultValue") else ""
        lines.append(f"- {val_id}: {label}{is_default}")
        
    return "\n".join(lines)


@mcp.resource("autotask://user/info")
async def get_user_info() -> str:
    """Get information about the current API user."""
    result = _make_request("GET", "ThresholdInformation")
    if "error" in result:
        return f"Error fetching user info: {result['error']}"
        
    return json.dumps(result, indent=2)


@mcp.resource("autotask://billing-codes")
async def get_billing_codes_resource() -> str:
    """
    Get a list of all active Billing Codes (Work Types).
    Useful for finding the correct billing_code_id for time entries.
    """
    filters = [{"field": "isActive", "op": "eq", "value": True}]
    result = _query_entity("BillingCodes", filters)
    
    if "error" in result:
        return f"Error fetching billing codes: {result['error']}"
    
    items = result.get("items", [])
    lines = ["# Active Billing Codes (Work Types)"]
    for item in items:
        lines.append(f"- {item.get('id')}: {item.get('name')}")
        
    return "\n".join(lines)


@mcp.resource("autotask://roles")
async def get_roles_resource() -> str:
    """
    Get a list of all active Roles.
    Useful for finding the correct role_id for time entries.
    """
    filters = [{"field": "isActive", "op": "eq", "value": True}]
    result = _query_entity("Roles", filters)
    
    if "error" in result:
        return f"Error fetching roles: {result['error']}"
    
    items = result.get("items", [])
    lines = ["# Active Roles"]
    for item in items:
        lines.append(f"- {item.get('id')}: {item.get('name')}")
        
    return "\n".join(lines)


@mcp.resource("autotask://queues")
async def get_queues_resource() -> str:
    """
    Get a list of all Ticket Queues.
    Useful for finding the correct queue_id for tickets.
    """
    # Queues are best retrieved from the Ticket entity picklist
    result = _make_request("GET", "Tickets/entityInformation/fields")
    
    if "error" in result:
        return f"Error fetching queues: {result['error']}"
    
    fields = result.get("fields", [])
    queue_field = next((f for f in fields if f.get("name") == "queueID"), None)
    
    if not queue_field:
        return "Error: queueID field not found in Tickets entity."
        
    values = queue_field.get("picklistValues", [])
    lines = ["# Ticket Queues"]
    for val in values:
        lines.append(f"- {val.get('value')}: {val.get('label')}")
        
    return "\n".join(lines)


# =============================================================================
# PROMPTS
# =============================================================================

@mcp.prompt()
def create_ticket_guide() -> str:
    """
    Returns a system prompt that helps the AI guide the user through creating a ticket.
    """
    return """You are an expert Autotask Ticket Manager.
When helping a user create a ticket, follow these steps:

1. **Identify the Company**: Ask for the company name if not provided. Use `autotask_search_companies` to find the ID.
2. **Identify the Contact**: If a contact is mentioned, find their ID using `autotask_search_contacts`.
3. **Determine Status and Priority**:
   - Check available statuses using the resource `autotask://picklist/Tickets/status`
   - Check available priorities using the resource `autotask://picklist/Tickets/priority`
4. **Draft the Ticket**: Confirm the details (Title, Description, Company, Priority) before calling `autotask_create_ticket`.

Always prefer using the `autotask://picklist/...` resources to find correct IDs for dropdown fields.
"""

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Validate configuration
    if not all([AUTOTASK_USERNAME, AUTOTASK_SECRET, AUTOTASK_INTEGRATION_CODE]):
        print("Warning: Autotask credentials not fully configured.")
        print("Please set the following environment variables:")
        print("  - AUTOTASK_USERNAME")
        print("  - AUTOTASK_SECRET")
        print("  - AUTOTASK_INTEGRATION_CODE")
        print("  - AUTOTASK_API_URL (optional, defaults to webservices16)")

    mcp.run()
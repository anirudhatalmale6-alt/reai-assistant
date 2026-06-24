from app.services import drive

TOOLS = [
    {
        "name": "search_drive_files",
        "description": "Search Google Drive for files and documents. Finds contracts, agreements, notes, reports, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (file name or content keywords)"},
                "max_results": {"type": "integer", "description": "Max files to return", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_drive_file",
        "description": "Read the content of a specific file from Google Drive by its file ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Google Drive file ID"},
            },
            "required": ["file_id"],
        },
    },
]

HANDLERS = {
    "search_drive_files": lambda params: drive.search_files(params["query"], params.get("max_results", 10)),
    "read_drive_file": lambda params: drive.read_file(params["file_id"]),
}

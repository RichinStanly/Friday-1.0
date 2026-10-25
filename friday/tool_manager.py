from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Callable, Any
from friday.tools import ToolEngine, ToolResult
from friday.permission_manager import PermissionLevel, engine as perm_engine

logger = logging.getLogger(__name__)

@dataclass
class ToolDefinition:
    name: str
    description: str
    category: str
    enabled: bool = True
    requires_internet: bool = False
    requires_confirmation: bool = False
    permission_level: PermissionLevel = PermissionLevel.SAFE
    execute: Callable[..., ToolResult] | None = None

class ToolManager(ToolEngine):
    """
    A minimal, safe Tool Manager abstraction that wraps the existing ToolEngine.
    This provides a stable registry/interface for future tools without breaking
    the existing hardcoded routing in chat.py.
    """
    def __init__(self, web_enabled: bool = False, store=None) -> None:
        super().__init__(web_enabled, store)
        self.registry: dict[str, ToolDefinition] = {}
        self.permissions = perm_engine
        if store:
            self.permissions.set_store(store)
        self._register_core_tools()

        self.register(ToolDefinition(name="clipboard_read", description="Read the clipboard", category="Clipboard", execute=self.clipboard_read))
        self.register(ToolDefinition(name="clipboard_write", description="Write to the clipboard", category="Clipboard", execute=self.clipboard_write))
        self.register(ToolDefinition(name="clipboard_clear", description="Clear the clipboard", category="Clipboard", execute=self.clipboard_clear))

        self.register(ToolDefinition(name="launch_app", description="Launch safe applications", category="Applications", execute=self.launch_app))
        self.register(ToolDefinition(name="process_info", description="Get system process and RAM info", category="System", execute=self.process_info))

        self.register(ToolDefinition(name="audio_control", description="Control volume", category="Audio", execute=self.audio_control))

        self.register(ToolDefinition(name="take_screenshot", description="Take a screenshot", category="Screen", execute=self.take_screenshot))

        self.register(ToolDefinition(name="archive_inspect", description="List contents of a ZIP file", category="Archives", execute=self.archive_inspect))
        self.register(ToolDefinition(name="archive_extract", description="Extract a ZIP file safely", category="Archives", execute=self.archive_extract))


    def _register_core_tools(self) -> None:
        self.register(ToolDefinition(
            name="search_web", description="Search the web via DuckDuckGo",
            category="Web Tools", requires_internet=True, execute=self.search_web
        ))
        self.register(ToolDefinition(
            name="fetch_webpage", description="Read text from a specific URL",
            category="Web Tools", requires_internet=True, execute=self.fetch_webpage
        ))

        self.register(ToolDefinition(
            name="search_images", description="Search for images",
            category="Media Tools", requires_internet=True, execute=self.search_images
        ))
        self.register(ToolDefinition(
            name="search_videos", description="Search for videos",
            category="Media Tools", requires_internet=True, execute=self.search_videos
        ))

        self.register(ToolDefinition(
            name="system_info", description="Get CPU/RAM usage and OS details",
            category="System Tools", execute=self.system_info
        ))
        self.register(ToolDefinition(
            name="run_shell", description="Run safe allowlisted shell commands",
            category="System Tools", execute=self.run_shell
        ))

        self.register(ToolDefinition(
            name="search_files", description="Search for files in the allowed workspace",
            category="File Tools", execute=self.search_files
        ))
        self.register(ToolDefinition(
            name="list_directory", description="List contents of a directory in the workspace",
            category="File Tools", execute=self.list_directory
        ))
        self.register(ToolDefinition(
            name="file_info", description="Get metadata for a file",
            category="File Tools", execute=self.file_info
        ))
        self.register(ToolDefinition(
            name="read_file", description="Read local text or PDF file contents",
            category="File Tools", execute=self.read_file
        ))
        self.register(ToolDefinition(
            name="open_file", description="Open a file using the host OS associated application",
            category="File Tools", execute=self.open_file
        ))
        self.register(ToolDefinition(
            name="delete_file", description="Delete a file from the workspace",
            category="File Tools", permission_level=PermissionLevel.CONFIRM, execute=self.delete_file
        ))

        self.register(ToolDefinition(
            name="memory_add", description="Add a fact to long-term memory",
            category="Memory Tools", execute=self.memory_add
        ))
        self.register(ToolDefinition(
            name="memory_list", description="List all memorized facts",
            category="Memory Tools", execute=self.memory_list
        ))

        self.register(ToolDefinition(
            name="calculator", description="Evaluate math expressions",
            category="Automation Tools", execute=self.calculator
        ))
        self.register(ToolDefinition(
            name="time_and_date", description="Get the current local time",
            category="Automation Tools", execute=self.time_and_date
        ))

    def register(self, tool: ToolDefinition) -> None:
        self.registry[tool.name] = tool

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self.registry.get(name)

    def execute_tool(self, name: str, *args, **kwargs) -> ToolResult | None:
        tool = self.get_tool(name)
        if not tool or not tool.enabled or not tool.execute:
            return None

        if tool.requires_internet and not self.web_enabled:
            return ToolResult(tool.name, "This tool requires internet access, which is currently disabled.", False)

        if not self.permissions.check_permission(tool.permission_level, tool.name, str(args), tool.description):
            return ToolResult(tool.name, f"Execution blocked or denied by user.")

        try:
            return tool.execute(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return ToolResult(tool.name, f"Error executing tool: {e}", False)

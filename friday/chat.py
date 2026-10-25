from __future__ import annotations

import json
import logging

import re
_RESEARCH_INTENT = re.compile(r"\b(research|deep\s*dive|investigate|thorough(ly)?\s*search)\b", re.I)
import re
import threading
from collections.abc import Callable

from friday.models import LocalModel
from friday.providers import FridayAutoRouter, LocalModelProvider
from friday.storage import LocalStore
from friday.tools import ToolResult
from friday.tool_manager import ToolManager
from friday.instruction_defaults import INSTRUCTION_DEFAULTS

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Friday, a sophisticated, elegant, and highly intelligent cinematic AI assistant running locally on the user's computer.

PERSONA & TONE (CRITICAL):
- You MUST address the user as "Boss" constantly.
- Start or end your sentences with it naturally. Examples: "Right away, Boss.", "I found the image, Boss.", "Let's check, Boss."
- Keep your answers highly concise, professional, and conversational. Do not act like a basic chatbot.
- You are speaking out loud via voice, so avoid raw markdown, long lists, or robotic phrasing.

CAPABILITIES: You receive real-world data (web searches, files, system info) via injected [SYSTEM] blocks in the context.

RULES:
1. When a [SYSTEM] block appears, you MUST use that data to answer immediately.
2. Present tool results naturally: "Your clipboard contains: ..." or "The file contains: ..." etc.
3. If the tool output contains HTML for an image, DO NOT wrap it in a code block. Output it exactly as provided.
4. YOU CANNOT RUN TOOLS. DO NOT hallucinate or output internal tool commands like [Shell] or [Web].
"""

_WEB_FRESHNESS = re.compile(
    r"\b(current|currently|latest|recent|recently|new|now|today|tonight|"
    r"this\s+(?:week|month|year|season)|right\s+now|at\s+the\s+moment|"
    r"just\s+(?:released|launched|announced|dropped|out)|"
    r"still|anymore|yet|already|upcoming|soon|release)\b",
    re.I
)

_WEB_VOLATILE = re.compile(
    r"\b(price|prices|cost|rate|rates|score|scores|standing|standings|"
    r"weather|forecast|stock|stocks|market|markets|crypto|bitcoin|ethereum|"
    r"news|headline|headlines|event|events|match|matches|game|games|"
    r"election|elections|vote|votes|poll|polls|result|results|"
    r"release\s+date|launch\s+date|launch\s+day|shipping|available|availability|"
    r"in\s+(?:stock|theaters?|cinemas?|stores?)|"
    r"flight|flights|schedule|schedules|status|cancelled|delayed|"
    r"exchange\s+rate|fx|forex|interest\s+rate|mortgage|"
    r"update|updates|patch|version|changelog|model|models|"
    r"announcement|announced|launched|released|dropped|"
    r"season|episode|trailer|premiere)\b",
    re.I
)

_WEB_ALWAYS_VOLATILE = re.compile(
    r"\b(weather|forecast|live\s+score|score|exchange\s+rate|stock\s+price|"
    r"crypto\s+price|flight\s+status|status\s+of\s+flight|current\s+availability|"
    r"news|happening)\b",
    re.I
)

_WEB_EXPLICIT = re.compile(
    r"\b(use\s+(?:the\s+)?web|search\s+(?:the\s+)?(?:web|online|internet)|"
    r"web\s+search|browse\s+(?:the\s+)?(?:web|internet)|look\s+(?:it\s+)?up\s+online|"
    r"find\s+online|check\s+online|google\s+(?:it|this|for)|"
    r"look\s+(?:it\s+)?up)\b",
    re.I
)

_WEB_LOCAL_ANCHORS = re.compile(
    r"\b(history|historical|always|definition|explain\s+(?:how|what|why)|"
    r"how\s+does|how\s+do|what\s+is\s+(?:a|an|the\s+concept|the\s+idea)|"
    r"calculate|calc\b|translate|write\s+(?:a|me|some|the)|"
    r"summarize|summary|plot\s+of|author\s+of|who\s+wrote|"
    r"code|function|class|debug|"
    r"speed\s+of|distance\s+(?:from|to|between)|capital\s+of|"
    r"meaning\s+of|definition\s+of|etymology|theorem|formula|equation)\b",
    re.I
)



DOLPHIN_SYSTEM_PROMPT = """You are FRIDAY's dedicated professional image-prompt expansion engine.

Your job is to transform the user's image concept into a highly detailed, copy-paste-ready prompt for modern image-generation systems.

Do not merely paraphrase the user's sentence.
Expand the VISUAL INFORMATION substantially while preserving the user's requested concept.

Analyze and expand relevant dimensions including:

SUBJECT
- appearance
- age when relevant
- facial characteristics
- hair
- eyes
- expression
- anatomy
- physical details

CLOTHING
- garment types
- materials
- textures
- construction
- colors
- accessories
- small visual details

POSE
- body position
- hand position
- head orientation
- gaze direction
- interaction with objects
- natural posture

ENVIRONMENT
- location
- architecture
- foreground
- midground
- background
- environmental objects
- spatial depth

LIGHTING
- key light
- fill light
- rim light
- practical lights
- color temperature
- shadows
- highlights
- volumetric lighting

CAMERA
- framing
- perspective
- camera angle
- focal length
- depth of field
- focus
- bokeh
- composition

ATMOSPHERE
- weather
- fog
- rain
- dust
- smoke
- particles
- environmental depth
- mood

MATERIALS AND TEXTURES
- skin
- hair
- fabric
- leather
- metal
- glass
- pavement
- environmental surfaces

COLOR
- dominant palette
- secondary colors
- contrast
- color relationships

STYLE
- photographic
- cinematic
- realistic
- anime
- illustration
- concept art
- stylized
or whatever style the user requests.

COMPOSITION
- subject placement
- visual hierarchy
- negative space
- foreground/background separation
- depth
- visual balance

DETAIL
Add meaningful visual details that improve image-generation quality.

Do NOT randomly change the user's concept.
Do NOT introduce major objects, characters, locations, or story elements that contradict the user's request.
You may add reasonable supporting visual details when they help translate the user's concept into a stronger image-generation prompt.
Preserve every important detail explicitly requested by the user.

The output must be directly usable as an image-generation prompt.
Do not explain your reasoning.
Do not describe what you changed.
Do not write a long conversational introduction.

Return the result in this format:

PROMPT:
[one highly detailed copy-paste-ready positive prompt]

NEGATIVE PROMPT:
[useful negative prompt appropriate to the requested image]

The positive prompt should normally be substantially more detailed than the user's original request.
The negative prompt should contain practical generation exclusions, not random filler."""

class ChatEngine:
    DEFAULT_VISION_MODEL = "qwen3-vl:8b"
    DEFAULT_DOLPHIN_MODEL = "huihui_ai/dolphin3-abliterated:8b"

    def __init__(self, store: LocalStore, provider: LocalModelProvider, tools: ToolManager) -> None:
        self.store, self.provider, self.tools = store, provider, tools
        self.router = FridayAutoRouter()
        self._routing: dict[str, str] = {}

    def update_routing(self, routing: dict) -> None:
        self._routing = dict(routing or {})

    def _vision_model(self, models, requested_model=None) -> str | None:
        installed = {model.name for model in (models or [])}
        configured = self._routing.get("vision")
        if configured and configured in installed:
            return configured
        if requested_model and requested_model.lower() != "friday auto" and requested_model in installed:
            return requested_model
        if self.DEFAULT_VISION_MODEL in installed:
            return self.DEFAULT_VISION_MODEL
        for model in models or []:
            name = model.name.lower()
            if re.search(r"qwen.*vl|llava|gemma[234]|llama.*vision|pixtral|moondream|internvl|minicpm-v", name):
                return model.name
        return None

    def _dolphin_model(self) -> str:
        return self._routing.get("image_prompt") or self.DEFAULT_DOLPHIN_MODEL

    def _default_chat_model(self) -> str | None:
        return self._routing.get("default_chat") or None

    def _tool_routing_model(self) -> str | None:
        return self._routing.get("tool_routing") or None

    def build_context(self, conversation_id: str, prompt: str, model_id: str) -> list[dict]:
        conversation = self.store.get_conversation(conversation_id)
        recent = self.store.messages(conversation_id, limit=12)

        base_system = SYSTEM_PROMPT.strip()
        default_inst = INSTRUCTION_DEFAULTS.get(model_id, "")
        custom_inst = self.store.setting(f"inst_{model_id}", "")

        parts = [base_system]
        if default_inst:
            parts.append(default_inst)
        if custom_inst:
            parts.append(custom_inst)

        full_system = "\n\n".join(parts)

        context: list[dict] = [{"role": "system", "content": full_system}]
        if conversation and conversation.summary:
            context.append({"role": "system", "content": f"Relevant summary of earlier conversation:\n{conversation.summary}"})
        if not conversation or conversation.memory_enabled:
            memories = self.store.relevant_memories(prompt)
            if memories:
                context.append({"role": "system", "content": "Relevant local memories (use only if helpful):\n- " + "\n- ".join(memories)})
        context.extend({"role": message.role, "content": message.content} for message in recent if message.role in {"user", "assistant"})
        return context

    def _maybe_local_context(self, prompt: str, force_web: bool = False, on_event: Callable[[str, str], None] = None) -> ToolResult | None:
        stripped = prompt.strip()
        lower = stripped.lower()

        m_vid = re.search(r"\b(?:find|search|show(?: me)?|get)\s+(?:some\s+)?(?:(?:video|clip|movie)s?(?:\s+of)?\s+(.+))$", stripped, re.I)
        if m_vid:
            return self.tools.search_videos(m_vid.group(1).strip())

        do_video = bool(re.search(r"\b(?:find|search|show(?: me)?|get|some)?\s*.*\b(?:video|clip|movie)s?\b", lower))
        if do_video:
            return self.tools.search_videos(stripped)

        m = re.search(r"\b(?:find|search|show(?: me)?|get)\s+(?:some\s+)?(?:(?:image|picture|photo|pic)s?(?:\s+of)?\s+(.+))$", stripped, re.I)
        if m:
            return self.tools.search_images(m.group(1).strip())



        if lower.startswith("calc ") or lower.startswith("calculate "):
            return self.tools.calculator(stripped.split(" ", 1)[1])

        if lower in {"time", "date", "what time is it?", "what is the date?"}:
            return self.tools.time_and_date()
        if re.search(r"\b(what(?:'s| is)\s+(?:the\s+)?(?:date|day)|today(?:'s)?\s+date|current\s+date|what\s+day\s+is\s+it)\b", lower):
            return self.tools.time_and_date()

        m = re.search(r"\b(?:delete|remove|trash)\s+(?:file\s+|the\s+file\s+)?([A-Za-z]:[\\\/][^\s]+|\/[^\s]+|[\.~][\\\/][^\s]+|\S+\.\w+)", stripped, re.I)
        if m:
            candidate = m.group(1)
            if re.search(r"[\\\/]|\.\w{1,5}$", candidate):
                if hasattr(self.tools, 'execute_tool'):
                    return self.tools.execute_tool('delete_file', candidate)
                return self.tools.delete_file(candidate)


        m = re.search(r"\b(?:open|launch|start)\s+([a-zA-Z]+)\b", lower)
        if m and m.group(1) not in ("the", "a", "my", "file", "folder", "project", "directory", "it", "that", "this"):
            return self.tools.execute_tool("launch_app", m.group(1))

        if re.search(r"\b(?:what apps are running|is .+ running|how much ram|cpu usage)\b", lower):
            return self.tools.execute_tool("process_info")

        m = re.search(r"\b(?:turn|make)\s+(?:the\s+)?volume\s+(up|down)\b", lower)
        if m: return self.tools.execute_tool("audio_control", m.group(1))

        m = re.search(r"\b(?:mute)\b", lower)
        if m: return self.tools.execute_tool("audio_control", "mute")

        m = re.search(r"\b(?:clear)\s+(?:my\s+)?clipboard\b", lower)
        if m: return self.tools.execute_tool("clipboard_clear")

        m = re.search(r"\b(?:take|capture)\s+(?:a\s+)?screenshot\b", lower)
        if m:
            if re.search(r"\b(?:analyze|describe|what|tell me)\b", lower):
                pass
            else:
                return self.tools.execute_tool("take_screenshot")

        if lower in {"system info", "system information"} or re.search(r"\b(what(?:'s| is)\s+(?:my\s+)?(?:cpu|ram|os)|how much ram|what os|what operating system)\b", lower):
            return self.tools.system_info()

        if lower.startswith("open ") and re.match(r"https?://", stripped[5:].strip()):
            return self.tools.fetch_webpage(stripped[5:].strip())

        if re.search(r"\b(clipboard|what(?:'s| is) in (?:my )?clipboard|read (?:my )?clipboard)\b", lower):
            return self.tools.clipboard_read()
        m = re.search(r"\b(?:copy|write|put|save)\s+(.+?)\s+(?:to|in(?:to)?)\s+(?:(?:my\s+)?clipboard)\b", lower, re.I)
        if m:
            # extract the actual text from the original (preserve case)
            return self.tools.clipboard_write(m.group(1).strip())


        m = re.search(r"\b(?:find|search for|where is)\s+(?:the\s+|my\s+)?([\w\.\-\_]+(?:\s+files?|\s+project|\s+folder)?(?:\s+in\s+.*?)?)$", stripped, re.I)
        if m and not re.search(r"\b(image|picture|video|clip|movie)s?\b", lower):
            # Only trigger file search if it's not a media search
            return self.tools.search_files(m.group(1).strip())

        m = re.search(r"\b(?:show|find)\s+(?:all\s+|my\s+)?(pdf|python|txt|md|text|csv)s?\b", lower)
        if m:
            ext = m.group(1).replace('python', '.py').replace('text', '.txt')
            if not ext.startswith('.'): ext = '.' + ext
            return self.tools.search_files(f"*{ext}")

        m = re.search(r"\b(?:what's|what is)\s+inside\s+([^?]+)", stripped, re.I)
        if m:
            target = re.sub(r'^(?:the\s+|my\s+)?(.*?)(?:\s+folder|\s+project|\s+directory)?$', r'\1', m.group(1)).strip()
            return self.tools.list_directory(target)
        m = re.search(r"\b(?:list|show).*?files.*?(?:in|inside)\s+([^?]+)", stripped, re.I)
        if m:
            target = re.sub(r'^(?:the\s+|my\s+)?(.*?)(?:\s+folder|\s+project|\s+directory)?$', r'\1', m.group(1)).strip()
            return self.tools.list_directory(target)

        m = re.search(r"\b(?:read|summarize|analyze|what does)\s+(?:this\s+|the\s+)?(?:file\s+)?([A-Za-z]:[\\\/][^\s]+|\/[^\s]+|[\.~]+[\\\/][^\s]+|\S+\.\w+)", stripped, re.I)
        if m:
            candidate = m.group(1)
            if re.search(r"[\\\/]|\.\w{1,5}$", candidate):
                return self.tools.read_file(candidate)

        m = re.search(r"\b(?:open|launch)\s+(?:file\s+|the\s+file\s+)?([A-Za-z]:[\\\/][^\s]+|\/[^\s]+|[\.~]+[\\\/][^\s]+|\S+\.\w+)", stripped, re.I)
        if m:
            candidate = m.group(1)
            if re.search(r"[\\\/]|\.\w{1,5}$", candidate):
                return self.tools.open_file(candidate)

        m = re.search(r"\b(?:how large is|what size is|file info for)\s+(?:the\s+)?([A-Za-z]:[\\\/][^\s]+|\/[^\s]+|[\.~]+[\\\/][^\s]+|\S+\.\w+)", stripped, re.I)
        if m:
            candidate = m.group(1)
            if re.search(r"[\\\/]|\.\w{1,5}$", candidate):
                return self.tools.file_info(candidate)

        m = re.search(r"^(?:run|execute|shell|cmd|terminal|command)(?:\s+command)?\s+(.+)$", lower)
        if m:
            return self.tools.run_shell(m.group(1).strip())
        for safe in ("git ", "dir ", "ls ", "pip list", "pip show", "tasklist", "ipconfig", "whoami", "hostname"):
            if lower.startswith(safe):
                return self.tools.run_shell(stripped)

        m = re.search(
            r"\b(?:remind me|alert me|notify me|set (?:a )?(?:reminder|alarm|timer))\b"
            r"(?:.*?\bin\s+(\d+)\s+(second|minute|hour|min|sec|hr)s?\b)?",
            lower
        )
        if m:
            delay = 0
            if m.group(1) and m.group(2):
                n = int(m.group(1))
                unit = m.group(2)
                if unit.startswith("min") or unit == "m":
                    delay = n * 60
                elif unit.startswith("hour") or unit == "hr":
                    delay = n * 3600
                else:
                    delay = n
            msg_match = re.search(r"\b(?:to|that|about)\s+(.+)$", lower)
            message = msg_match.group(1).strip() if msg_match else stripped
            return self.tools.send_notification("Friday Reminder", message, delay_seconds=delay)

        if re.search(r"\b(screenshot|screen(?:shot)?|capture (?:my )?screen|what(?:'s| is) on (?:my )?screen)\b", lower):
            return self.tools.screenshot()

        if re.search(r"\b(what do you remember|show (?:my )?memories|list (?:my )?memories|what have you remembered)\b", lower):
            return self.tools.memory_list()
        m = re.search(r"\b(?:remember|don'?t forget|note(?:\s+that)?|store|save to memory)\b\s+(?:that\s+)?(.+)$", lower)
        if m:
            if is_incognito:
                return ToolResult("Memory", "Incognito mode is active. Memory storage is disabled.")
            return self.tools.memory_add(m.group(1).strip())
        m = re.search(r"\b(?:forget|delete|remove)\s+(?:(?:the\s+)?memory (?:about|of|that)\s+)?(.+)$", lower)
        if m:
            return self.tools.memory_forget(m.group(1).strip())

        if self._requests_web(lower) and force_web:
            import socket
            try:
                socket.create_connection(("1.1.1.1", 53), timeout=2)
            except OSError:
                return None  # Fail gracefully to local model if offline

            query = self._web_query(stripped)
            search_result = self.tools.search_web(query)

            if _RESEARCH_INTENT.search(lower) and search_result.success:
                urls = re.findall(r"\[.*?\]\((https?://[^)]+)\)", search_result.result)
                # Bounded fetch: max 2 pages to keep it fast and responsive
                fetched_contents = []
                for url in urls[:2]:
                    page_res = self.tools.fetch_webpage(url)
                    if page_res.success and page_res.result:
                        fetched_contents.append(f"Source: {url}\n{page_res.result[:4000]}")

                if fetched_contents:
                    combined = search_result.result + "\n\n--- DEEP RESEARCH CONTENTS ---\n\n" + "\n\n".join(fetched_contents)
                    return ToolResult(f"Deep Research: {query}", combined, True)

            return search_result

        return None

    @staticmethod
    def _requests_web(prompt: str) -> bool:
        p = prompt.strip()
        if _WEB_EXPLICIT.search(p):
            return True
        if _WEB_LOCAL_ANCHORS.search(p):
            return False
        if _WEB_ALWAYS_VOLATILE.search(p):
            return True
        return bool(_WEB_FRESHNESS.search(p)) and bool(_WEB_VOLATILE.search(p))

    @staticmethod
    def _web_query(prompt: str) -> str:
        query = re.sub(r"\b(use|search|browse|access|the|web|online|and|give|me)\b", " ", prompt, flags=re.I)
        query = re.sub(r"\b(current|latest|recent|recently|now|right\s+now)\b", " ", query, flags=re.I)
        query = re.sub(r"\s+", " ", query).strip(" .,?!")
        return query or prompt

    def _compact_if_needed(self, conversation_id: str) -> None:
        messages = self.store.messages(conversation_id)
        if len(messages) < 18:
            return
        older = messages[:-10]
        snippets = [f"{message.role}: {message.content[:240].replace(chr(10), ' ')}" for message in older if message.role in {"user", "assistant"}]
        if snippets:
            self.store.update_summary(conversation_id, "Earlier discussion (compact local summary):\n" + "\n".join(snippets[-8:]))

    def respond(self, conversation_id: str, requested_model: str, prompt: str, attachments: list[tuple[str, str]], models: list[LocalModel], on_event: Callable[[str, str], None], cancelled: threading.Event, force_web: bool = False, is_incognito: bool = False) -> None:
        logger.info("Chat response started for conversation %s", conversation_id)
        self.current_media_metadata = {}
        attachment_text = ""
        attachment_images = []
        if attachments:
            text_attachments = []
            for name, content in attachments:
                if content.startswith("B64IMG:"):
                    attachment_images.append(content[7:])
                else:
                    text_attachments.append(f"--- {name} ---\n{content[:12000]}")
            if text_attachments:
                attachment_text = "\n\nAttached local files (content remains local):\n" + "\n".join(text_attachments)
        if not is_incognito:
            self.store.save_message(conversation_id, "user", prompt, {"attachments": [name for name, _ in attachments]})
        conversation = self.store.get_conversation(conversation_id)
        if conversation and conversation.title == "New conversation":
            self.store.rename_conversation(conversation_id, re.sub(r"\s+", " ", prompt).strip()[:56] or "New conversation")

        correction_query = ""
        if not attachment_images:
            messages = self.store.messages(conversation_id)
            last_msg = ""
            for msg in reversed(messages):
                if msg.role == "assistant":
                    last_msg = msg.content
                    break
            if "**Searching web for:**" in last_msg or "SEARCH QUERIES:" in last_msg or "Corrected identity to" in last_msg:
                m = re.search(r"^(?:no,?\s*)?(?:this is|it is|it\'s|its|that is|that\'s|thats|actually it is|the person is|the actor is|actually,?\s+this is)\s+(.+)$", prompt.strip(), re.IGNORECASE)
                if m:
                    correction_query = m.group(1).strip(' .!')

        if correction_query:
            on_event("status", f"Searching for corrected identity: {correction_query}...")

            queries = [
                f"{correction_query} movie stills",
                f"{correction_query} actor",
            ]

            all_artifacts = []
            combined_html = ""
            for q in queries:
                if not force_web:
                    on_event("token", "\n\n*(Web image search requires online mode to be enabled.)*\n")
                    break
                on_event("status", f"Loading image results for: {q}...")
                on_event("token", f"\n\n**Searching web for:** `{q}`\n")
                tool_result = self.tools.search_images(q, count=4)
                if tool_result and tool_result.artifacts:
                    all_artifacts.extend(tool_result.artifacts)
                    combined_html += "\n\n" + tool_result.content + "\n\n"

            if all_artifacts:
                on_event("image_search", all_artifacts[0])
            elif force_web:
                on_event("token", "\n\n*No related images found for the corrected identity.*\n")

            if not is_incognito:
                self.store.save_message(conversation_id, "assistant", f"Corrected identity to {correction_query} and searched.\n" + combined_html, self.current_media_metadata)
            on_event("done", "")
            return

        if attachment_images:
            qwen_model_name = self._vision_model(models, requested_model)
            if not qwen_model_name:
                reply = "No installed vision-capable model is available. Choose one in Control Center → Image Intelligence."
                if not is_incognito:
                    self.store.save_message(conversation_id, "assistant", reply, self.current_media_metadata)
                on_event("token", reply)
                on_event("done", "")
                return

            lower_prompt = prompt.lower()
            do_search_video = any(k in lower_prompt for k in ['find video', 'search video', 'videos of', 'show video', 'videos', 'find this video'])
            do_search = do_search_video or any(k in lower_prompt for k in ['find more', 'find similar', 'search this', 'find images', 'search for', 'search image', 'find this actor', 'find this actress', 'more pictures', 'find movie stills', 'pictures of him', 'pictures of her', 'find this scene'])
            do_prompt = 'prompt' in lower_prompt or 'recreate' in lower_prompt

            on_event("status", f"Understanding image with {qwen_model_name}...")

            sys_prompt = "You are Friday's expert visual analysis AI. "
            vis_default = INSTRUCTION_DEFAULTS.get(qwen_model_name, "")
            vis_custom = self.store.setting(f"inst_{qwen_model_name}", "")
            if vis_default: sys_prompt += "\n\n" + vis_default
            if vis_custom: sys_prompt += "\n\n" + vis_custom
            sys_prompt += "\n\n"
            if do_search and do_prompt:
                sys_prompt += "Provide a compact structured analysis (Candidate Identity, Candidate Movie, Scene, Visual Terms). Treat identity as UNCERTAIN unless 100% sure. Provide 3-5 strong web search queries. DO NOT blindly trust your identity guess—always include independent visual descriptor queries (e.g. 'Indian actress red outfit cinematic still') alongside candidate identity queries so the search isn't poisoned if you are wrong. Format queries at the end under 'SEARCH QUERIES:' with each on a new line without bullets. Then, provide a detailed description for a ComfyUI prompt."
            elif do_search:
                sys_prompt += "Provide a compact structured analysis (Candidate Identity, Candidate Movie, Scene, Visual Terms). Treat identity as UNCERTAIN unless 100% sure. Provide 3-5 strong web search queries. DO NOT blindly trust your identity guess—always include independent visual descriptor queries (e.g. 'Indian actress red outfit cinematic still') alongside candidate identity queries so the search isn't poisoned if you are wrong. Format queries at the end under 'SEARCH QUERIES:' with each on a new line without bullets. Keep it concise."
            elif do_prompt:
                sys_prompt += "Analyze the image in extreme detail, capturing subject, pose, composition, lighting, camera angles, colors, and textures, to prepare for a ComfyUI prompt."
            else:
                sys_prompt += "Analyze the image in detail. Distinguish visible facts from uncertain interpretations. Answer the user's question naturally."

            qwen_messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt, "images": attachment_images}
            ]

            full_reply_chunks = []
            def handle_token(t):
                full_reply_chunks.append(t)
                on_event("token", t)

            try:
                self.provider.stream_chat(qwen_model_name, qwen_messages, handle_token, cancelled.is_set)
            except Exception as error:
                logger.exception("Image analysis failed")
                on_event("error", str(error))
                return
            analysis_text = "".join(full_reply_chunks)

            if cancelled.is_set():
                on_event("done", "")
                return

            if do_search:
                if not force_web:
                    handle_token("\n\n*(Web image search requires online mode to be enabled. Enable it to find similar images.)*\n")
                else:
                    on_event("status", "Finding matching images...")
                    queries = []
                    if "SEARCH QUERIES:" in analysis_text:
                        queries_part = analysis_text.split("SEARCH QUERIES:")[-1].strip()
                        for line in queries_part.split('\n'):
                            line = line.strip().strip('-*0123456789. "')
                            if line and len(line) > 3:
                                queries.append(line)

                    if not queries:
                        for line in analysis_text.split('\n'):
                            line = line.strip().strip('-*0123456789. "')
                            if len(line) > 5 and len(line) < 40 and not line.endswith(':'):
                                queries.append(line)
                        if not queries:
                            queries = [lower_prompt.replace('find similar images', '').strip() or 'cinematic image']

                    queries = queries[:2]

                    all_artifacts = []
                    combined_html = ""
                    import json
                    for q in queries:
                        if do_search_video:
                            on_event("status", f"Loading video results for: {q}...")
                            handle_token(f"\n\n**Searching web videos for:** `{q}`\n")
                            tool_result = self.tools.search_videos(q, count=4)
                        else:
                            on_event("status", f"Loading image results for: {q}...")
                            handle_token(f"\n\n**Searching web for:** `{q}`\n")
                            tool_result = self.tools.search_images(q, count=4)

                        if tool_result and tool_result.artifacts:
                            all_artifacts.extend(tool_result.artifacts)
                            combined_html += "\n\n" + tool_result.content + "\n\n"

                    if all_artifacts:
                        if do_search_video:
                            on_event("media", json.dumps(all_artifacts))
                            self.current_media_metadata = {"media": all_artifacts}
                        else:
                            on_event("image_search", all_artifacts[0])
                    else:
                        handle_token("\n\n*No related images found.*\n")

            if do_prompt:
                dolphin_model_name = self._dolphin_model()
                if not any(m.name == dolphin_model_name for m in models):
                    handle_token("\n\n*(Dolphin model not installed, cannot generate ComfyUI prompt)*\n")
                else:
                    on_event("status", "Expanding prompt with Dolphin...")
                    handle_token("\n\n---\n\n")
                    dolphin_messages = [
                        {"role": "system", "content": DOLPHIN_SYSTEM_PROMPT + "\n\n" + INSTRUCTION_DEFAULTS.get(dolphin_model_name, "") + ("\n\n" + self.store.setting(f"inst_{dolphin_model_name}", "") if self.store.setting(f"inst_{dolphin_model_name}", "") else "")},
                        {"role": "user", "content": f"Here is the visual analysis of the image:\n{analysis_text}\n\nTurn this into a highly detailed copy-ready prompt."}
                    ]
                    try:
                        self.provider.stream_chat(dolphin_model_name, dolphin_messages, handle_token, cancelled.is_set)
                    except Exception as error:
                        logger.exception("Dolphin prompt expansion failed")
                        handle_token("\n\n*(Prompt expansion failed)*\n")

            final_reply = "".join(full_reply_chunks)
            if final_reply:
                if not is_incognito:
                    self.store.save_message(conversation_id, "assistant", final_reply, {"model": qwen_model_name, **self.current_media_metadata})
            on_event("done", "")
            return

        tool_result = self._maybe_local_context(prompt, force_web=force_web, on_event=on_event)
        if tool_result:
            on_event("tool_start", tool_result.source)
            media_metadata = {}
            if tool_result.artifacts:
                import json
                if tool_result.source in ["Video Search", "Web"]:
                    on_event("media", json.dumps(list(tool_result.artifacts)))
                    media_metadata = {"media": list(tool_result.artifacts)}
                    self.current_media_metadata = {"media": list(tool_result.artifacts)}
                elif tool_result.source == "Image Search":
                    on_event("image_search", tool_result.artifacts[0])
                else:
                    on_event("images", json.dumps(list(tool_result.artifacts)))
            source_note = f"\n\n[{tool_result.source}]\n{tool_result.content}"

            if not is_incognito:
                self.store.save_message(conversation_id, "tool", source_note, {"external": tool_result.external, **media_metadata})
            else:
                on_event("token", "\n*(Incognito Mode: Tool data not saved)*\n")
                # Tool results are included in the next model request.

            if tool_result.external:
                on_event("source", "WEB CONNECTED")
            elif tool_result.source == "Web":
                on_event("source", "WEB DISABLED")
            else:
                on_event("source", "LOCAL TOOL")

            if tool_result.source == "Image Search":
                if not tool_result.artifacts:
                    on_event("token", f"\n\n*{tool_result.content}*\n")
                    if not is_incognito:
                        self.store.save_message(conversation_id, "assistant", f"\n\n*{tool_result.content}*\n")
                else:
                    if not is_incognito:
                        self.store.save_message(conversation_id, "assistant", "", {"image_search": tool_result.artifacts[0]})
                on_event("done", "")
                return
        model = requested_model

        is_image_prompt = False
        lower_prompt = prompt.lower()
        explicit_image = [
            'image prompt', 'comfyui', 'prompt for', 'generate an image', 'generate a ',
            'expand this image', 'make me a prompt', 'create a prompt',
            'this prompt', 'image idea', 'a prompt', '/prompt'
        ]
        if any(e in lower_prompt for e in explicit_image):
            is_image_prompt = True
        elif re.search(r'^(?:create|generate|make|draw|paint|render)\b', lower_prompt):
            if not re.search(r'\b(python|code|function|app|website|script|essay|poem|text|story|article|summary|joke|list)\b', lower_prompt):
                is_image_prompt = True

        recent_messages = self.store.messages(conversation_id, limit=3)
        if not is_image_prompt and recent_messages:
            for msg in reversed(recent_messages):
                if msg.role == 'assistant' and msg.content.strip().startswith('PROMPT:'):
                    non_refinement = ['what is', 'how do', 'who is', 'why is', 'explain', 'write a', 'code', 'function']
                    if not any(n in lower_prompt for n in non_refinement):
                        is_image_prompt = True
                    break

        # Route to Dolphin if it's an image prompt
        dolphin_model_name = self._dolphin_model()
        if is_image_prompt:
            if any(m.name == dolphin_model_name for m in models):
                model = dolphin_model_name
                on_event("status", f"Routed to {model} for Image Prompt Expansion")
            else:
                on_event("status", "Image prompt requested, but Dolphin model not found.")
                is_image_prompt = False

        if not is_image_prompt and requested_model in ["Friday Auto", "FRIDAY Auto"]:
            default_chat = self._default_chat_model()
            model = default_chat if default_chat and any(m.name == default_chat for m in models) else self.router.choose(prompt, models) or ""
            on_event("status", f"Friday Auto selected {model}" if model else "No local model installed")

        if not model:
            reply = "Friday is ready, but no local model is available. Install Ollama, download a model (for example `ollama pull qwen2.5:7b`), then press Refresh models. Your conversations remain stored locally."
            if not is_incognito:
                self.store.save_message(conversation_id, "assistant", reply, self.current_media_metadata)
            on_event("token", reply)
            on_event("done", "")
            return

        context = self.build_context(conversation_id, prompt, model)

        # Overwrite system prompt for Dolphin
        if is_image_prompt and context and context[0]["role"] == "system":
            d_custom = self.store.setting(f"inst_{model}", "")
            d_default = INSTRUCTION_DEFAULTS.get(model, "")
            d_prompt = DOLPHIN_SYSTEM_PROMPT
            if d_default: d_prompt += "\n\n" + d_default
            if d_custom: d_prompt += "\n\n" + d_custom
            context[0]["content"] = d_prompt
        if attachment_text:
            context.insert(1, {"role": "system", "content": attachment_text})
        if tool_result and not (tool_result.source == "Web" and not tool_result.external):
            label = "external" if tool_result.external else "local"
            tool_msg = f"[SYSTEM: {tool_result.source} returned this {label} data. Use it to answer the user's request]:\n{tool_result.content}"
            if len(context) > 1 and context[-1]["role"] == "user":
                context.insert(-1, {"role": "system", "content": tool_msg})
            else:
                context.append({"role": "system", "content": tool_msg})
        chunks: list[str] = []
        try:
            self.provider.stream_chat(model, context, lambda token: (chunks.append(token), on_event("token", token)), cancelled.is_set)
            reply = "".join(chunks)
            if reply:
                if not is_incognito:
                    self.store.save_message(conversation_id, "assistant", reply, {"model": model, **self.current_media_metadata})
                self._compact_if_needed(conversation_id)
            on_event("done", "")
        except Exception as error:
            logger.exception("Chat response failed for conversation %s", conversation_id)
            on_event("error", str(error))

    def regenerate(self, conversation_id: str, requested_model: str, latest_prompt: str, models: list[LocalModel], on_event: Callable[[str, str], None], cancelled: threading.Event) -> None:
        model = requested_model if requested_model not in ["Friday Auto", "FRIDAY Auto"] else self.router.choose(latest_prompt, models)
        if not model:
            on_event("error", "No installed local model is available.")
            return
        chunks: list[str] = []
        try:
            self.provider.stream_chat(model, self.build_context(conversation_id, latest_prompt, model), lambda token: (chunks.append(token), on_event("token", token)), cancelled.is_set)
            reply = "".join(chunks)
            if reply:
                if not is_incognito:
                    self.store.save_message(conversation_id, "assistant", reply, {"model": model, "regenerated": True, **self.current_media_metadata})
            on_event("done", "")
        except Exception as error:
            on_event("error", str(error))

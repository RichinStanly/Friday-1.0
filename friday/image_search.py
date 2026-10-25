import logging
import urllib.request
import urllib.parse
import json
import re
import os
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ImageSearchResult:
    def __init__(self, title, image_url, thumbnail_url, source_url, source_name, provider, width, height, format, filesize=None, description=""):
        self.title = title
        self.image_url = image_url
        self.thumbnail_url = thumbnail_url
        self.source_url = source_url
        self.source_name = source_name
        self.provider = provider
        self.width = width
        self.height = height
        self.resolution = f"{width}x{height}" if width and height else "Unknown"
        self.format = format
        self.filesize = filesize
        self.description = description

        self.rank_score = 0
        self.quality = "Unknown"
        self._classify_quality()

    def _classify_quality(self):
        if not self.width or not self.height:
            return
        w, h = self.width, self.height
        if w >= 7680 or h >= 4320:
            self.quality = "8K"
            self.rank_score += 100
        elif w >= 3840 or h >= 2160:
            self.quality = "4K"
            self.rank_score += 80
        elif w >= 2560 or h >= 1440:
            self.quality = "High"
            self.rank_score += 60
        elif w >= 1920 or h >= 1080:
            self.quality = "Good"
            self.rank_score += 40
        else:
            self.quality = "Low"
            self.rank_score += 20

    def to_dict(self):
        return self.__dict__

class SearXNGProvider:
    def __init__(self):
        self.urls = ["http://127.0.0.1:8080", "https://searx.be"]

    def search(self, query: str, page: int = 1) -> List[ImageSearchResult]:
        results = []
        for instance_url in self.urls:
            try:
                url = f"{instance_url}/search?q={urllib.parse.quote(query)}&categories=images&pageno={page}&format=json"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    for r in data.get('results', []):
                        img_src = r.get('img_src')
                        if img_src:
                            width = r.get('width', 0)
                            height = r.get('height', 0)
                            try:
                                width = int(width) if width else 0
                                height = int(height) if height else 0
                            except:
                                width = height = 0

                            results.append(ImageSearchResult(
                                title=r.get('title', ''),
                                image_url=img_src,
                                thumbnail_url=r.get('thumbnail_src', img_src),
                                source_url=r.get('url', ''),
                                source_name=r.get('parsed_url', [None, 'Unknown'])[1] if r.get('parsed_url') else 'Unknown',
                                provider=f"SearXNG/{r.get('engine', 'Unknown')}",
                                width=width,
                                height=height,
                                format=r.get('img_format', 'Unknown'),
                            ))
                if results:
                    break
            except Exception:
                continue
        return results

class DDGProvider:
    def search(self, query: str, page: int = 1) -> List[ImageSearchResult]:
        results = []
        try:
            from ddgs import DDGS
            max_r = page * 50
            ddg_results = DDGS().images(query, max_results=max_r, safesearch='off')

            start = (page - 1) * 50
            end = page * 50
            page_results = ddg_results[start:end]

            for r in page_results:
                width = r.get('width', 0)
                height = r.get('height', 0)
                try:
                    width = int(width) if width else 0
                    height = int(height) if height else 0
                except:
                    width = height = 0

                results.append(ImageSearchResult(
                    title=r.get('title', ''),
                    image_url=r.get('image'),
                    thumbnail_url=r.get('thumbnail', r.get('image')),
                    source_url=r.get('url', ''),
                    source_name=r.get('source', 'Unknown'),
                    provider="DDG",
                    width=width,
                    height=height,
                    format="Unknown",
                ))
        except Exception:
            pass
        return results

class BingProvider:
    def search(self, query: str, page: int = 1) -> List[ImageSearchResult]:
        results = []
        try:
            import urllib.request, urllib.parse, re, json
            first = (page - 1) * 35 + 1
            url = f'https://www.bing.com/images/async?q={urllib.parse.quote_plus(query)}&first={first}&count=35'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
            html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8')
            matches = re.findall(r'm="(\{.*?\})"', html)
            for m in matches:
                try:
                    data = json.loads(m.replace('&quot;', '"'))
                    murl = data.get('murl')
                    if murl:
                        results.append(ImageSearchResult(
                            title=data.get('t', ''),
                            image_url=murl,
                            thumbnail_url=data.get('turl', murl).replace('&amp;', '&'),
                            source_url=data.get('purl', ''),
                            source_name=data.get('desc', 'Unknown'),
                            provider="Bing",
                            width=0,  # Bing m block doesn't reliably give width/height
                            height=0,
                            format="Unknown"
                        ))
                except:
                    continue
        except Exception:
            pass
        return results

class ImageSearchHub:
    def __init__(self, store=None):
        self.providers = [SearXNGProvider(), DDGProvider(), BingProvider()]
        self.store = store

    def _enhance_query(self, query: str) -> str:
        q = query.strip()
        import re
        q = re.sub(r'^(?:search\s+images\s+of|find\s+images\s+of|pictures\s+of|photos\s+of)\s+', '', q, flags=re.IGNORECASE)
        q = ' '.join(q.split())
        return q or query

    def search_images(self, original_query: str, page: int = 1) -> tuple[str, List[ImageSearchResult]]:
        query = self._enhance_query(original_query)
        all_results = []
        for p in self.providers:
            all_results.extend(p.search(query, page))

        unique = self._deduplicate_and_rank(all_results)
        return query, unique

    def _deduplicate_and_rank(self, results: List[ImageSearchResult]) -> List[ImageSearchResult]:
        seen_urls = set()
        unique = []

        results.sort(key=lambda r: r.rank_score, reverse=True)

        for r in results:
            norm_img_url = r.image_url.lower().strip() if r.image_url else None

            # Reject missing or data-uri main images
            if not norm_img_url or norm_img_url.startswith('data:') or norm_img_url in seen_urls:
                continue

            # Reject obviously generic placeholder images
            lower_url = norm_img_url.lower()
            lower_title = r.title.lower() if r.title else ""
            if any(p in lower_url or p in lower_title for p in ['placeholder', 'no-image', 'no_image', 'default-avatar']):
                continue

            seen_urls.add(norm_img_url)
            unique.append(r)

        return unique

    def download_image(self, result: ImageSearchResult) -> str | None:
        save_dir = Path.home() / "Downloads" / "FridayImages"
        save_dir.mkdir(parents=True, exist_ok=True)

        if self.store:
            dl_index = self.store.setting("image_downloads", {})
            if result.image_url in dl_index:
                p = Path(dl_index[result.image_url])
                if p.exists():
                    return str(p)

        safe_title = "".join(c if c.isalnum() else "_" for c in (result.title or "image"))[:30]
        ext = "jpg"
        if result.image_url:
            url_ext = result.image_url.split('.')[-1].split('?')[0].lower()
            if url_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                ext = url_ext

        idx = 1
        while True:
            filename = f"{safe_title}_{idx:03d}.{ext}"
            filepath = save_dir / filename
            if not filepath.exists():
                break
            idx += 1

        try:
            req = urllib.request.Request(result.image_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response, open(filepath, 'wb') as out_file:
                out_file.write(response.read())

            if self.store:
                dl_index = self.store.setting("image_downloads", {})
                dl_index[result.image_url] = str(filepath)
                self.store.set_setting("image_downloads", dl_index)

            return str(filepath)
        except Exception:
            return None

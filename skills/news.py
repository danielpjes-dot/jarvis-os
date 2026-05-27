"""
JARVIS Skill — News by topic and optional location. Supports Telegram integration.

 Uses Google News RSS feeds.
 Returns structured UI result when supported by frontend.
 SKILL_NAME = "news"
 SKILL_DESCRIPTION = "News headlines by topic and optional location"
 SKILL_VERSION = "1.2.0"
 SKILL_AUTHOR = "Sami Porokka"
 SKILL_CATEGORY = "utility"
 SKILL_TAGS = ["news", "headlines", "location", "topic", "rss", "ui"]
 SKILL_REQUIREMENTS = []
 SKILL_RESPONSE_STYLE = {
     "default": "structured_news_ui",
     "avoid_raw_dump": True,
     "telegram": {
         "format": "markdown",
         "max_length": 4096,
         "support_inline_buttons": True
     },
     "followup_hint": True,
 }
"""Read-only tools eligible for research. Overview charging is a separate policy."""
from knowledge_tools import ALL_TOOLS as KNOWLEDGE_TOOLS

ALLOWED = {'search_bilibili_videos','get_video_metadata','get_video_transcript',
 'get_video_comments','get_video_chapters','search_bilibili_creators','get_bilibili_creator_content',
 'get_video_danmaku','get_video_context','get_video_comment_threads','check_bilibili_credentials',
 'watch_video','sample_video_frames','get_frames','get_frame_at','read_external_image'}

ALLOWED |= KNOWLEDGE_TOOLS | {'read_rss_subscription','get_bilibili_article'}

// Field-level feedback for existing argument checks. No new validation rules.
export function checkArguments(code, checks) {
 const problems=checks.filter(([,ok])=>!ok).slice(0,8).map(([field,,message])=>({field,message}));
 if(problems.length)throw Object.assign(new Error(code),{code,argumentErrors:problems,argumentDetail:problems.map(p=>`${p.field}: ${p.message}`).join('; ')});
}
export function argumentError(code) {
 const hints={INVALID_BILIBILI_VIDEO:['bvid_or_url/page','Use a BV or Bilibili video URL and a positive integer part.'],
  VIDEO_PART_CONFLICT:['page','Explicit page must match the URL p value; omit page to use the URL part.'],
  INVALID_COMMENT_ARGUMENT:['bvid_or_url','Use a BV or Bilibili video URL.']};
 const hint=hints[code];return Object.assign(new Error(code),{code,...(hint?{argumentErrors:[{field:hint[0],message:hint[1]}],argumentDetail:hint.join(': ')}:{})});
}

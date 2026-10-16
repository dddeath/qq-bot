import test from 'node:test';
import assert from 'node:assert/strict';
import {createAdapter} from '../adapter.mjs';

const result = data => ({content:[{type:'text',text:JSON.stringify(data)}]});
test('empty search and bounded comments retain their actual scope',async()=>{
  const empty=await createAdapter(async()=>result({results:[]})).call('search_bilibili_videos',{query:'none'});
  assert.deepEqual(empty.data.results,[]);assert.equal(empty.status,'ok');
  const r=await createAdapter(async()=>result({comments:[{content:'社区看法'}],summary:{total_comments:1}})).call('get_video_comments',{bvid_or_url:'BV1234567890',limit:20});
  assert.equal(r.completeness,'bounded_comment_sample');
  assert.equal(r.scope.requested_limit,20);
  assert.equal(r.scope.complete,false);
});
test('missing subtitles, expired login and transport failures keep distinct error states',async()=>{
  for(const code of ['SUBTITLE_UNAVAILABLE','COOKIE_EXPIRED']) {
    const adapter=createAdapter(async()=>({...result({error:{code,message:'controlled error'}}),isError:true}));
    const r=await adapter.call('get_video_transcript',{bvid_or_url:'BV1234567890'});
    assert.equal(r.status,'error');assert.equal(r.error.code,code);
    assert.equal(r.completeness,'unavailable');
  }
  const r=await createAdapter(async()=>{throw new Error('private cookie');}).call('get_video_metadata',{bvid_or_url:'BV1234567890'});
  assert.equal(r.error.code,'UPSTREAM_FAILURE');
  assert.ok(!JSON.stringify(r).includes('private cookie'));
});
test('a mismatched returned BV is not passed to the researcher as valid material',async()=>{
  const r=await createAdapter(async()=>result({bvid:'BV0987654321',transcript:'wrong'})).call('get_video_transcript',{bvid_or_url:'BV1234567890'});
  assert.equal(r.status,'error');assert.equal(r.error.code,'BV_MISMATCH');assert.equal(r.data,null);
});
test('only approved read tools and subtitle-only requests reach upstream',async()=>{
  const calls=[];
  const adapter=createAdapter(async(name,args)=>{calls.push({name,args});return result({bvid:'BV1234567890',segments:[{from:2,to:4,content:'冰的密度低'}]});});
  await assert.rejects(()=>adapter.call('list_bilibili_favorite_videos',{}),/tool_not_allowed/);
  await assert.rejects(()=>adapter.call('get_video_transcript',{bvid_or_url:'BV1234567890',force_asr:true}),/asr_disabled/);
  const r=await adapter.call('get_video_transcript',{bvid_or_url:'BV1234567890'});
  assert.equal(calls.length,1);
  assert.equal(calls[0].args.fallback_to_asr,false);
  assert.equal(calls[0].args.force_asr,false);
  assert.equal(calls[0].args.include_timestamps,true);
  assert.equal(r.data.segments[0].from,2);
  assert.equal(r.source.url,'https://www.bilibili.com/video/BV1234567890/');
  assert.equal(r.completeness,'returned_subtitle_scope');
});
test('search returns source material, acquisition time and measured duration', async()=>{
  const adapter = createAdapter(async()=>result({results:[{bvid:'BV1234567890',title:'游戏攻略',source_url:'https://www.bilibili.com/video/BV1234567890/'}]}));
  const r=await adapter.call('search_bilibili_videos',{query:'游戏攻略'});
  assert.equal(r.platform,'bilibili');
  assert.equal(r.data.results[0].title,'游戏攻略');
  assert.equal(r.status,'ok');
  assert.equal(r.completeness,'first_page_only');
  assert.ok(Number.isFinite(r.elapsed_ms));
  assert.ok(Number.isFinite(Date.parse(r.fetched_at)));
});

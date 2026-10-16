import test from 'node:test';
import assert from 'node:assert/strict';
import {readCommentThreads} from '../comment-threads.mjs';

test('thread pages preserve IDs, reply targets, raw emoji and continuation',async()=>{
 const api=async(path,args)=>path.endsWith('/view')?{aid:12,bvid:'BV1KXYc6aEFR',owner:{mid:7}}:
 {page:{num:2,size:2,count:5},root:{rpid_str:'9007199254740993',content:{message:'主楼'},member:{mid:'7',uname:'UP'}},
 replies:[{rpid_str:'22',root_str:'9007199254740993',parent_str:'21',ctime:123,like:4,member:{mid:'8',uname:'甲'},content:{message:'反话[doge]'}},
 {rpid_str:'23',root_str:'9007199254740993',parent_str:'22',member:{mid:'7',uname:'UP'},content:{message:'对'}}]};
 const r=await readCommentThreads({bvid_or_url:'BV1KXYc6aEFR',root_id:'9007199254740993',page:2,page_size:2},api);
 assert.equal(r.items[0].parent_id,'21');assert.equal(r.items[0].root_id,'9007199254740993');
 assert.equal(r.items[0].text,'反话[doge]');assert.equal(r.items[1].is_uploader,true);
 assert.equal(r.next_page,3);assert.equal(r.remaining,1);assert.equal(r.root.id,'9007199254740993');
});

test('top-level roots remain navigable and invalid pages never reach the API',async()=>{
 const api=async path=>path.endsWith('/view')?{aid:12,bvid:'BV1KXYc6aEFR',owner:{mid:7}}:
 {page:{count:1},replies:[{rpid:10,root:0,parent:0,rcount:8,member:{mid:9},content:{message:'笑死[doge]'}}]};
 const r=await readCommentThreads({bvid_or_url:'BV1KXYc6aEFR'},api);
 assert.equal(r.items[0].root_id,'10');assert.equal(r.items[0].reply_count,8);
 assert.equal(r.next_page,null);
 await assert.rejects(readCommentThreads({bvid_or_url:'BV1KXYc6aEFR',page_size:21},()=>{throw Error('network called');}),{code:'INVALID_COMMENT_ARGUMENT'});
});

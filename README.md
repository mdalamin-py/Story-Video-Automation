# Story Video Automation

## নমুনা

PowerShell-এ এই ফোল্ডার খুলে চালান।

    .\run.cmd draft --demo
    .\run.cmd render RUN_NAME

প্রথম কমান্ড যে Run নাম দেখায়, দ্বিতীয় কমান্ডে সেটি দিন। `runs/RUN_NAME/preview.mp4`-তে রঙিন ফ্রেমসহ বাংলা ক্যাপশনের নমুনা পাওয়া যাবে।

## নিজের গল্প ও শেষ মুহূর্তের পরিবর্তন

1. `input/brief.json`-এর `story`-তে আপনার গল্প বা আইডিয়া লিখুন। `final_changes`-এ শেষ মুহূর্তের নির্দেশ দিন। একই ফাইলে ভাষা, ভিডিও স্টাইল, দৈর্ঘ্য, অডিও ও ক্যাপশন বদলান। 1080p ভার্টিক্যাল ডিফল্ট।
2. `.env.example` কপি করে `.env` বানান। OpenAI API key ও আপনার অ্যাকাউন্টে চালু থাকা Responses API model দিন। FFmpeg PATH-এ, `FFMPEG_PATH`-এ, অথবা Python-এর imageio-ffmpeg প্যাকেজে থাকতে হবে। ক্যাপশনের জন্য FFmpeg-এ libass প্রয়োজন।
3. `.\run.cmd draft` চালিয়ে `runs/RUN_NAME/plan.json` দেখুন। দৃশ্য, সংলাপ, ক্যাপশন বা পোস্টের লেখা এখানেই সম্পাদনা করুন। নতুন শেষ নির্দেশ দিয়ে গল্প আবার লেখাতে ইনপুট বদলে আবার draft চালান।
4. `.\run.cmd render RUN_NAME` চালান। আপনার কেনা সার্ভিস **muse-video.com** হলে `MUSE_PROVIDER=muse-video.com` এবং `MUSE_API_KEY` সেট করুন। অন্য Muse সার্ভিস হলে তার adapter লাগবে। সম্পাদনার পর নতুন ভিডিও রেন্ডার করতে ক্রেডিট লাগতে পারে। নিজের MP4 ব্যবহার করতে `.\run.cmd render RUN_NAME --video "D:\my-video.mp4"` চালান।
5. `preview.mp4`-তে দৃশ্য, শব্দ ও উচ্চারণ মিলিয়ে নিন। আপলোডের জন্য `made_for_kids` ও `synthetic_disclosure` কনটেন্ট অনুযায়ী সেট করুন।

## আপলোড ও অটোমেশন

YouTube Data API সক্রিয় Google OAuth client এবং `youtube.upload` অনুমতিসহ refresh token দিন। Facebook-এর জন্য Page ID, Page access token ও Graph API version দিন। Credentials স্থানীয় `.env`-এ রাখুন।

    .\run.cmd upload RUN_NAME --platform both
    .\run.cmd upload RUN_NAME --platform both --public
    .\run.cmd auto --platform both --public

প্রথম কমান্ড YouTube private ও Facebook draft হিসেবে জমা দেয়। দ্বিতীয়টি সরাসরি public জমা দেয়। তৃতীয়টি বর্তমান গল্প ও শেষ নির্দেশ নিয়ে গল্প লেখা থেকে আপলোড পর্যন্ত একবারে চালায়। `auto`-তে মাঝখানে প্রিভিউ দেখে থামতে চাইলে আলাদা draft, render ও upload কমান্ড ব্যবহার করুন।

একই রানে সফল প্ল্যাটফর্ম পুনরায় জমা হয় না। Private বা draft থেকে public করতে সংশ্লিষ্ট প্ল্যাটফর্মের Studio ব্যবহার করুন। সংযোগ বিচ্ছিন্ন হলে পুনরায় জমা দেওয়ার আগে প্ল্যাটফর্মে ফল যাচাই করুন। Muse-এ আটকে থাকলে একই রান দিয়ে render চালিয়ে polling চালু করুন।

- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Muse Video API](https://muse-video.com/docs/api)
- [YouTube Data API](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)
- [Facebook Reels API](https://www.postman.com/meta/facebook/request/juhnm3q/4-publish-reel)

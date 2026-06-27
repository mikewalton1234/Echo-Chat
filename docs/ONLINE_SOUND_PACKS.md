# Online JavaScript sound packs

Echo-Chat can load sound packs from online HTTPS `.js` files. The scripts are fetched by the browser before the split chat runtime parts, so the sound code does not have to live in `/static/js/sound_packs` on the Echo-Chat server.

## Admin setup

1. Upload a sound-pack `.js` file to an HTTPS host, or use a compatible online JavaScript library URL.
2. Open **Admin Panel → System → Notification sounds**.
3. Paste the URL into **Online sound-pack .js URLs**. Use one URL per line.
4. Save.
5. Hard-reload the browser tab.
6. Choose the sound pack and per-event sounds.
7. Press **Test** beside each event sound before saving the final route.
8. After the online pack works, turn off **Also load local built-in sound packs** if you do not want the local fallback files loaded.

## Known online JavaScript library bridge

Echo-Chat automatically recognizes this browser UMD library when the admin loads it as an online `.js` URL:

```text
https://cdn.jsdelivr.net/npm/simple-notification-sounds@1.0.0/dist/simple-notification-sounds.umd.js
```

After saving that URL and hard-reloading, the admin sound dropdowns will include **Simple Notification Sounds CDN** options such as attention, alert, success, warning, and error sounds in short/medium/long variants.

## Sound-pack script shape: generated Web Audio

```js
(function () {
  const pack = {
    id: "my_online_pack",
    file: "https://example.com/my_online_pack.js",
    label: "My online sound pack",
    description: "Generated or custom browser sounds.",
    sounds: [
      { id: "my_ping", label: "My ping", description: "Short ping" },
      { id: "my_alert", label: "My alert", description: "Attention alert" }
    ],
    play(soundId, ctx, h, kind) {
      const now = ctx.currentTime + 0.01;
      if (soundId === "my_ping") {
        h.tone(ctx, now, 0.14, 880, { type: "sine", volume: 0.035 });
        return;
      }
      if (soundId === "my_alert") {
        h.tone(ctx, now, 0.12, 520, { type: "triangle", volume: 0.045 });
        h.tone(ctx, now + 0.12, 0.16, 780, { type: "triangle", volume: 0.035 });
      }
    }
  };

  if (window.EchoChatSoundPacks && typeof window.EchoChatSoundPacks.register === "function") {
    window.EchoChatSoundPacks.register(pack);
  } else {
    window.EC_PENDING_SOUND_PACKS = Array.isArray(window.EC_PENDING_SOUND_PACKS) ? window.EC_PENDING_SOUND_PACKS : [];
    window.EC_PENDING_SOUND_PACKS.push(pack);
  }
})();
```

## Sound-pack script shape: Remote MP3/WAV URLs

This format lets the `.js` file stay online and point to online sound files. Echo-Chat plays `https://` or `data:audio/` URLs directly in the browser. Some sound hosts may block hotlinking; if a sound does not play, download it under its license and host it from your own HTTPS storage/CDN.

```js
(function () {
  const pack = {
    id: "my_remote_audio_pack",
    file: "https://example.com/my_remote_audio_pack.js",
    label: "My remote audio pack",
    description: "Online MP3/WAV sounds for chat events.",
    sounds: [
      {
        id: "remote_chat_pop",
        label: "Remote chat pop",
        description: "Incoming chat/message pop.",
        url: "https://example.com/audio/chat-pop.mp3",
        volume: 0.6
      },
      {
        id: "remote_invite_bell",
        label: "Remote invite bell",
        description: "Invite or friend request bell.",
        url: "https://example.com/audio/invite-bell.wav",
        volume: 0.55
      }
    ]
  };

  if (window.EchoChatSoundPacks && typeof window.EchoChatSoundPacks.register === "function") {
    window.EchoChatSoundPacks.register(pack);
  } else {
    window.EC_PENDING_SOUND_PACKS = Array.isArray(window.EC_PENDING_SOUND_PACKS) ? window.EC_PENDING_SOUND_PACKS : [];
    window.EC_PENDING_SOUND_PACKS.push(pack);
  }
})();
```

## Validation rules

- Only HTTPS URLs are accepted for online sound-pack scripts.
- Sound-pack script URLs must end in `.js`.
- Username/password credentials inside URLs are rejected.
- Echo-Chat automatically adds configured sound-pack origins to the default Content-Security-Policy.
- Remote audio URLs inside a trusted sound-pack script must be `https://` or `data:audio/` to play through the built-in remote-audio fallback.

## Admin Panel shortcut buttons

The Admin Panel sound card includes three helper buttons:

- **Open sound-pack guide** opens this local Markdown guide from a protected admin route.
- **Open sound source list** opens the companion review list in `docs/ONLINE_CHAT_SOUND_SOURCES.md`.
- **Copy SNS CDN URL** copies the tested Simple Notification Sounds UMD URL so it can be pasted into **Online sound-pack .js URLs**.

After adding or changing online sound-pack URLs, save the settings and hard-reload each client tab. The scripts must load before the split chat runtime files so their sounds appear in the pack and event dropdowns.

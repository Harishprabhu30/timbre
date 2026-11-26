"use strict";

// Synthetic float32 RIFF/WAVE input. Preserve the source rate and frame count
// by copying directly into an AudioBuffer instead of using decodeAudioData.
function legacyFixture(wav) {
    const binary = atob(wav);
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const data = new DataView(bytes.buffer);
    if (binary.slice(0, 4) !== "RIFF" || binary.slice(8, 12) !== "WAVE") {
        throw new Error("Expected RIFF/WAVE");
    }

    let channels, sampleRate, encoding, blockAlign, bits, offset, frames;
    for (let chunk = 12; chunk + 8 <= bytes.length;) {
        const kind = binary.slice(chunk, chunk + 4);
        const size = data.getUint32(chunk + 4, true);
        const start = chunk + 8;
        if (start + size > bytes.length) throw new Error("Truncated WAV chunk");
        if (kind === "fmt " && size >= 16) {
            encoding = data.getUint16(start, true);
            channels = data.getUint16(start + 2, true);
            sampleRate = data.getUint32(start + 4, true);
            blockAlign = data.getUint16(start + 12, true);
            bits = data.getUint16(start + 14, true);
        } else if (kind === "data") {
            offset = start;
            frames = size / blockAlign;
        }
        chunk = start + size + (size % 2);
    }
    if (encoding !== 3 || bits !== 32 || (channels !== 1 && channels !== 2) ||
        blockAlign !== channels * 4 || !sampleRate || !Number.isInteger(frames) || frames < 1) {
        throw new Error("Expected a nonempty mono or stereo IEEE float32 fixture");
    }
    return { data, channels, sampleRate, blockAlign, offset, frames };
}

function legacyEncode(rendered, warmup, frames) {
    const channels = rendered.numberOfChannels;
    const sampleRate = rendered.sampleRate;
    const byteCount = frames * channels * 4;
    const bytes = new Uint8Array(44 + byteCount);
    const data = new DataView(bytes.buffer);
    bytes.set([82, 73, 70, 70], 0);                 // RIFF
    data.setUint32(4, 36 + byteCount, true);
    bytes.set([87, 65, 86, 69, 102, 109, 116, 32], 8); // WAVEfmt
    data.setUint32(16, 16, true);
    data.setUint16(20, 3, true);
    data.setUint16(22, channels, true);
    data.setUint32(24, sampleRate, true);
    data.setUint32(28, sampleRate * channels * 4, true);
    data.setUint16(32, channels * 4, true);
    data.setUint16(34, 32, true);
    bytes.set([100, 97, 116, 97], 36);              // data
    data.setUint32(40, byteCount, true);

    for (let channel = 0; channel < channels; channel++) {
        const audio = rendered.getChannelData(channel);
        for (let frame = 0; frame < frames; frame++) {
            data.setFloat32(44 + (frame * channels + channel) * 4, audio[warmup + frame], true);
        }
    }

    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 32_768) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
    }
    return btoa(binary);
}

window.renderLegacyFixture = async function (wav, config) {
    const fixture = legacyFixture(wav);
    // Let existing engine AudioParam automation settle before the first sample.
    // Remove exactly this many frames from the render, without delay fitting.
    const warmup = Math.round(fixture.sampleRate * 0.25);
    const context = new OfflineAudioContext(2, warmup + fixture.frames, fixture.sampleRate);
    const buffer = context.createBuffer(fixture.channels, fixture.frames, fixture.sampleRate);
    for (let channel = 0; channel < fixture.channels; channel++) {
        const audio = buffer.getChannelData(channel);
        for (let frame = 0; frame < fixture.frames; frame++) {
            audio[frame] = fixture.data.getFloat32(fixture.offset + frame * fixture.blockAlign + channel * 4, true);
        }
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(window.makeLegacyResearchGraph(context, config));
    source.start(warmup / fixture.sampleRate);

    return legacyEncode(await context.startRendering(), warmup, fixture.frames);
};

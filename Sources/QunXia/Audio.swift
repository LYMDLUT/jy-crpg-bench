import AudioToolbox
import Foundation
import CoreHost

/// Drains the core's audio ring into CoreAudio. Without this the game is silent.
final class AudioOut {
    private var queue: AudioQueueRef?
    private var buffers: [AudioQueueBufferRef] = []
    private let bufferCount = 4
    private let bufferFrames = 1024
    private(set) var muted = false

    func start(sampleRate: Double) -> Bool {
        var fmt = AudioStreamBasicDescription(
            mSampleRate: sampleRate,
            mFormatID: kAudioFormatLinearPCM,
            mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked,
            mBytesPerPacket: 4,
            mFramesPerPacket: 1,
            mBytesPerFrame: 4,
            mChannelsPerFrame: 2,
            mBitsPerChannel: 16,
            mReserved: 0
        )

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        var q: AudioQueueRef?
        let status = AudioQueueNewOutput(&fmt, { userData, aq, buf in
            guard let userData else { return }
            Unmanaged<AudioOut>.fromOpaque(userData).takeUnretainedValue().fill(aq, buf)
        }, selfPtr, nil, nil, 0, &q)
        guard status == noErr, let q else { return false }
        queue = q

        for _ in 0..<bufferCount {
            var buf: AudioQueueBufferRef?
            guard AudioQueueAllocateBuffer(q, UInt32(bufferFrames * 4), &buf) == noErr, let buf else { return false }
            buffers.append(buf)
            fill(q, buf)
        }
        return AudioQueueStart(q, nil) == noErr
    }

    func setMuted(_ m: Bool) {
        muted = m
        if let queue { AudioQueueSetParameter(queue, kAudioQueueParam_Volume, m ? 0 : 1) }
    }

    func stop() {
        if let queue {
            AudioQueueStop(queue, true)
            AudioQueueDispose(queue, true)
        }
        queue = nil
        buffers.removeAll()
    }

    private func fill(_ aq: AudioQueueRef, _ buf: AudioQueueBufferRef) {
        let dst = buf.pointee.mAudioData.assumingMemoryBound(to: Int16.self)
        let got = core_audio_read(dst, bufferFrames)
        if got < bufferFrames {
            // Underrun: pad with silence rather than stalling the queue.
            memset(dst + got * 2, 0, (bufferFrames - got) * 4)
        }
        buf.pointee.mAudioDataByteSize = UInt32(bufferFrames * 4)
        AudioQueueEnqueueBuffer(aq, buf, 0, nil)
    }
}

#!/usr/bin/env swift
//
// 从 docs/logo.svg 重新生成 macOS 图标集。
//
// 为什么不用 sips 直接压 docs/logo-1024.png：那张图是白底 flattened PNG，
// 四角不透明（右下角还有一个杂色像素）。Finder / IconServices 会原样读取
// icns 里的 PNG，于是图标在深色背景上会出现难看的白方块。
// 这里用 AppKit 按矢量渲染，保留 SVG 的透明圆角，再交给 iconutil 打包。
//
// 用法：swift tools/pack/make_icon.swift docs/logo.svg build/pack/icon.iconset
//
import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write(
        "usage: make_icon.swift <input.svg|png> <output.iconset>\n".data(using: .utf8)!
    )
    exit(2)
}
let input = args[1]
let outDir = args[2]

guard let image = NSImage(contentsOfFile: input), image.size.width > 0, image.size.height > 0 else {
    FileHandle.standardError.write("cannot load image: \(input)\n".data(using: .utf8)!)
    exit(1)
}

try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

// Apple 要求的 iconset 尺寸：16/32/128/256/512 及各自 @2x。
let sizes: [(Int, String)] = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

for (pixels, name) in sizes {
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        FileHandle.standardError.write("cannot allocate \(pixels)x\(pixels)\n".data(using: .utf8)!)
        exit(1)
    }
    rep.size = NSSize(width: pixels, height: pixels)
    NSGraphicsContext.saveGraphicsState()
    if let context = NSGraphicsContext(bitmapImageRep: rep) {
        NSGraphicsContext.current = context
        context.cgContext.clear(CGRect(x: 0, y: 0, width: pixels, height: pixels))
        image.draw(
            in: NSRect(x: 0, y: 0, width: pixels, height: pixels),
            from: .zero,
            operation: .sourceOver,
            fraction: 1.0
        )
        context.flushGraphics()
    }
    NSGraphicsContext.restoreGraphicsState()
    guard let png = rep.representation(using: .png, properties: [:]) else {
        FileHandle.standardError.write("cannot encode \(name)\n".data(using: .utf8)!)
        exit(1)
    }
    do {
        try png.write(to: URL(fileURLWithPath: (outDir as NSString).appendingPathComponent(name)))
    } catch {
        FileHandle.standardError.write("cannot write \(name): \(error)\n".data(using: .utf8)!)
        exit(1)
    }
}
print("iconset written: \(outDir)")

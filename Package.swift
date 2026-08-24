// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "QunXia",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "QunXia", targets: ["QunXia"])
    ],
    targets: [
        .target(
            name: "CoreHost",
            path: "Sources/CoreHost",
            publicHeadersPath: "include",
            cSettings: [
                .headerSearchPath("include"),
            ],
            linkerSettings: []
        ),
        .executableTarget(
            name: "QunXia",
            dependencies: ["CoreHost"],
            path: "Sources/QunXia",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("Metal"),
                .linkedFramework("MetalKit"),
                .linkedFramework("QuartzCore"),
                .linkedFramework("Network"),
                .linkedFramework("CoreGraphics"),
                .linkedFramework("ImageIO"),
                .linkedFramework("UniformTypeIdentifiers"),
            ]
        )
    ]
)

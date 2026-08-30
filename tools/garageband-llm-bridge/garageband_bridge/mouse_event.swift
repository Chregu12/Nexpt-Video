import CoreGraphics
import Foundation

func usage() -> Never {
    fputs("usage: mouse_event.swift click X Y | drag X1 Y1 X2 Y2 [DELAY_SECONDS]\n", stderr)
    exit(2)
}

func point(_ x: String, _ y: String) -> CGPoint {
    guard let dx = Double(x), let dy = Double(y) else {
        usage()
    }
    return CGPoint(x: dx, y: dy)
}

func post(_ type: CGEventType, _ point: CGPoint) {
    guard let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left) else {
        fputs("could not create mouse event\n", stderr)
        exit(3)
    }
    event.post(tap: .cghidEventTap)
}

let args = CommandLine.arguments
if args.count < 4 {
    usage()
}

let command = args[1]

if command == "click" {
    if args.count != 4 { usage() }
    let p = point(args[2], args[3])
    post(.mouseMoved, p)
    usleep(50_000)
    post(.leftMouseDown, p)
    usleep(50_000)
    post(.leftMouseUp, p)
    print("\(Int(p.x)),\(Int(p.y))")
} else if command == "drag" {
    if args.count < 6 || args.count > 7 { usage() }
    let start = point(args[2], args[3])
    let end = point(args[4], args[5])
    let delay = args.count == 7 ? max(0.0, min(5.0, Double(args[6]) ?? 0.2)) : 0.2
    post(.mouseMoved, start)
    usleep(50_000)
    post(.leftMouseDown, start)
    let steps = 12
    for index in 1...steps {
        let t = Double(index) / Double(steps)
        let x = start.x + (end.x - start.x) * t
        let y = start.y + (end.y - start.y) * t
        post(.leftMouseDragged, CGPoint(x: x, y: y))
        usleep(useconds_t((delay / Double(steps)) * 1_000_000))
    }
    post(.leftMouseUp, end)
    print("\(Int(start.x)),\(Int(start.y))->\(Int(end.x)),\(Int(end.y))")
} else {
    usage()
}

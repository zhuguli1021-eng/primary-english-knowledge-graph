// OCR scanned PDF pages with macOS Vision (no extra deps).
// usage: swift ocr_pdf.swift <file.pdf> [firstPage] [lastPage]  (1-based, inclusive)
// output: "=== page N" then one line per text box: "x y text" (x,y = top-left, 0..1, y grows downward)
import AppKit
import PDFKit
import Vision

let args = CommandLine.arguments
guard args.count > 1 else {
    FileHandle.standardError.write("cannot open pdf\n".data(using: .utf8)!); exit(1)
}
let input = URL(fileURLWithPath: args[1])
let doc = PDFDocument(url: input)
let singleImage = doc == nil ? NSImage(contentsOf: input) : nil
let pageCount = doc?.pageCount ?? (singleImage == nil ? 0 : 1)
guard pageCount > 0 else { exit(1) }
let first = args.count > 2 ? Int(args[2])! : 1
let last = args.count > 3 ? Int(args[3])! : pageCount

for i in (first - 1)..<min(last, pageCount) {
    let page = doc?.page(at: i)
    let b = page?.bounds(for: .mediaBox) ?? CGRect(origin: .zero, size: singleImage!.size)
    let scale = 2200 / max(b.width, b.height)  // ponytail: fixed ~2200px long edge; raise if small print misreads
    let img = page?.thumbnail(of: CGSize(width: b.width * scale, height: b.height * scale), for: .mediaBox) ?? singleImage!
    var rect = CGRect(origin: .zero, size: img.size)
    guard let cg = img.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["en-GB", "zh-Hans"]
    req.usesLanguageCorrection = true
    try VNImageRequestHandler(cgImage: cg).perform([req])
    let obs = (req.results ?? []).sorted {
        let dy = $0.boundingBox.maxY - $1.boundingBox.maxY
        return abs(dy) > 0.008 ? dy > 0 : $0.boundingBox.minX < $1.boundingBox.minX
    }
    print("=== page \(i + 1)")
    for o in obs {
        guard let s = o.topCandidates(1).first?.string else { continue }
        print(String(format: "%.2f %.2f ", o.boundingBox.minX, 1 - o.boundingBox.maxY) + s)
    }
}

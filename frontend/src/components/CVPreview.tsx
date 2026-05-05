// Renders the generated CV HTML inside a sandboxed iframe.
// We use srcDoc (not src) so the HTML is self-contained and we don't have
// to serve it from a separate URL.

interface CVPreviewProps {
  html: string | null;
  pdfUrl: string | null;
}

export default function CVPreview({ html, pdfUrl }: CVPreviewProps) {
  if (!html) {
    return (
      <div
        style={{
          border: '1px dashed #cfcfd4',
          borderRadius: 8,
          padding: 32,
          color: '#6b6b75',
          textAlign: 'center',
          background: '#fff',
        }}
      >
        Your generated CV will appear here.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {pdfUrl && (
        <a
          href={pdfUrl}
          target="_blank"
          rel="noreferrer"
          style={{
            alignSelf: 'flex-end',
            padding: '6px 12px',
            background: '#111',
            color: '#fff',
            borderRadius: 6,
            textDecoration: 'none',
            fontSize: 14,
          }}
        >
          Download PDF
        </a>
      )}
      <iframe
        title="CV preview"
        srcDoc={html}
        sandbox="allow-same-origin"
        style={{
          width: '100%',
          height: '70vh',
          border: '1px solid #e2e2e8',
          borderRadius: 8,
          background: '#fff',
        }}
      />
    </div>
  );
}

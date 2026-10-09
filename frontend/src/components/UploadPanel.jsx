import { useId, useRef, useState, useCallback } from "react";
import {
  Check,
  CheckCircle2,
  FileSpreadsheet,
  FileUp,
  LoaderCircle,
  Upload,
  X,
} from "lucide-react";

// =============================================================================
// Constants & Validation
// =============================================================================

const DEFAULT_ACCEPT = ".csv,text/csv";
const MAX_FILE_SIZE_MB = 10;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isCsvFile(file) {
  if (!file) return false;

  const name = String(file.name || "").trim().toLowerCase();
  const type = String(file.type || "").trim().toLowerCase();

  return (
    name.endsWith(".csv") ||
    type === "text/csv" ||
    type === "application/csv"
  );
}

function validateFile(file) {
  if (!file) return "Choose a CSV file to continue.";

  if (!isCsvFile(file)) {
    return "This file format isn't supported. Please choose a CSV file.";
  }

  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `This file exceeds the ${MAX_FILE_SIZE_MB} MB upload limit.`;
  }

  return "";
}

function getUploadErrorMessage(error) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }

  return "We couldn't upload your file. Please try again.";
}

// =============================================================================
// UploadPanel Component
// =============================================================================

/**
 * @typedef {Object} UploadPanelProps
 * @property {(file: File) => Promise<void>|void} onUpload
 * @property {boolean} [loading=false]
 * @property {string} [accept=DEFAULT_ACCEPT]
 */

/**
 * UploadPanel component for handling drag-and-drop or file-picker CSV imports.
 * 
 * @param {UploadPanelProps} props
 */
export default function UploadPanel({
  onUpload,
  loading = false,
  accept = DEFAULT_ACCEPT,
}) {
  const id = useId();
  const inputRef = useRef(null);

  const [selectedFile, setSelectedFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const titleId = `${id}-title`;
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  const inputId = `${id}-input`;

  const selectFile = useCallback((file) => {
    if (loading) return;

    setError("");
    setSuccess(false);

    const validationError = validateFile(file);

    if (validationError) {
      setSelectedFile(null);
      setError(validationError);
      return;
    }

    setSelectedFile(file);
  }, [loading]);

  function handleInputChange(event) {
    selectFile(event.target.files?.[0] || null);
    // Allow the same file to be selected again.
    event.target.value = "";
  }

  function handleDragOver(event) {
    event.preventDefault();
    event.stopPropagation();

    if (!loading) setIsDragging(true);
  }

  function handleDragLeave(event) {
    event.preventDefault();
    event.stopPropagation();

    const nextTarget = event.relatedTarget;

    if (
      nextTarget &&
      nextTarget instanceof Node &&
      event.currentTarget.contains(nextTarget)
    ) {
      return;
    }

    setIsDragging(false);
  }

  function handleDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);

    if (loading) return;

    const files = event.dataTransfer.files;
    selectFile(files?.[0] || null);
  }

  const openFilePicker = useCallback(() => {
    if (!loading) inputRef.current?.click();
  }, [loading]);

  function handleDropzoneKeyDown(event) {
    if (loading || selectedFile) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openFilePicker();
    }
  }

  function handleRemoveFile(event) {
    event?.stopPropagation();

    if (loading) return;

    setSelectedFile(null);
    setError("");
    setSuccess(false);
    setIsDragging(false);
  }

  async function handleUpload() {
    if (!selectedFile || loading) return;

    const validationError = validateFile(selectedFile);

    if (validationError) {
      setError(validationError);
      return;
    }

    if (typeof onUpload !== "function") {
      setError("Uploading is temporarily unavailable. Please try again later.");
      return;
    }

    try {
      setError("");
      setSuccess(false);

      await onUpload(selectedFile);

      setSelectedFile(null);
      setSuccess(true);
    } catch (uploadError) {
      setError(getUploadErrorMessage(uploadError));
    }
  }

  const dropzoneClasses = [
    "upload-dropzone",
    isDragging && "is-dragging",
    selectedFile && "has-file",
    loading && "is-loading",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section
      className="upload-panel"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <header className="upload-panel__header">
        <div className="upload-panel__heading">
          <div className="upload-panel__eyebrow">
            <span className="upload-panel__eyebrow-dot" />
            DATA IMPORT
          </div>

          <h2 id={titleId} className="upload-panel__title">
            Bring your energy data to life.
          </h2>

          <p
            id={descriptionId}
            className="upload-panel__description"
          >
            Upload a dataset to uncover consumption patterns,
            understand demand, and discover opportunities to save.
          </p>
        </div>

        <div className="upload-panel__header-icon" aria-hidden="true">
          <FileSpreadsheet size={23} strokeWidth={1.7} />
        </div>
      </header>

      <input
        ref={inputRef}
        id={inputId}
        className="upload-panel__input sr-only"
        type="file"
        accept={accept}
        onChange={handleInputChange}
        disabled={loading}
        aria-describedby={error ? errorId : descriptionId}
      />

      <div
        className={dropzoneClasses}
        onDragOver={handleDragOver}
        onDragEnter={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={!selectedFile ? openFilePicker : undefined}
        onKeyDown={handleDropzoneKeyDown}
        role={!selectedFile ? "button" : undefined}
        tabIndex={!selectedFile && !loading ? 0 : -1}
        aria-label="CSV file drop area. Click or press enter to browse files."
      >
        {!selectedFile ? (
          <div className="upload-dropzone__empty">
            <div className="upload-dropzone__visual" aria-hidden="true">
              <div className="upload-dropzone__visual-inner">
                <Upload size={25} strokeWidth={1.7} />
              </div>
              <span className="upload-dropzone__visual-spark">
                <FileSpreadsheet size={15} />
              </span>
            </div>

            <div className="upload-dropzone__content">
              <h3>Drop your dataset here</h3>
              <p>
                Drag and drop your CSV file, or{" "}
                <button
                  type="button"
                  className="upload-panel__browse"
                  onClick={(e) => {
                    e.stopPropagation();
                    openFilePicker();
                  }}
                  disabled={loading}
                >
                  browse files
                </button>
              </p>
            </div>

            <div className="upload-dropzone__meta">
              <span className="upload-dropzone__format">
                <FileSpreadsheet size={14} />
                CSV format
              </span>
              <span className="upload-dropzone__meta-divider" />
              <span>Maximum {MAX_FILE_SIZE_MB} MB</span>
            </div>
          </div>
        ) : (
          <div className="upload-file">
            <div className="upload-file__icon" aria-hidden="true">
              <FileSpreadsheet size={23} strokeWidth={1.7} />
            </div>

            <div className="upload-file__details">
              <h3 className="upload-file__name" title={selectedFile.name}>
                {selectedFile.name}
              </h3>
              <div className="upload-file__meta">
                <span>{formatFileSize(selectedFile.size)}</span>
                <span className="upload-file__separator" />
                <span className="upload-file__ready">
                  <CheckCircle2 size={13} />
                  Ready to import
                </span>
              </div>
            </div>

            <button
              type="button"
              className="upload-file__remove"
              onClick={handleRemoveFile}
              disabled={loading}
              aria-label={`Remove ${selectedFile.name}`}
              title="Remove file"
            >
              <X size={17} />
            </button>
          </div>
        )}
      </div>

      {error && (
        <div
          id={errorId}
          className="upload-panel__feedback upload-panel__feedback--error"
          role="alert"
        >
          <span className="upload-panel__feedback-icon" aria-hidden="true">
            <X size={15} />
          </span>
          <p>{error}</p>
          <button
            type="button"
            className="upload-panel__feedback-dismiss"
            onClick={() => setError("")}
            aria-label="Dismiss error"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {success && !error && (
        <div
          className="upload-panel__feedback upload-panel__feedback--success"
          role="status"
        >
          <span className="upload-panel__feedback-icon" aria-hidden="true">
            <Check size={15} />
          </span>
          <p>Your dataset was uploaded successfully.</p>
        </div>
      )}

      <footer className="upload-panel__footer">
        <div className="upload-panel__footer-copy">
          <span className="upload-panel__footer-icon" aria-hidden="true">
            <FileUp size={16} />
          </span>
          <div>
            <span className="upload-panel__footer-title">
              Ready when you are
            </span>
            <span className="upload-panel__footer-description">
              CSV files up to {MAX_FILE_SIZE_MB} MB
            </span>
          </div>
        </div>

        <button
          type="button"
          className="upload-panel__submit"
          onClick={handleUpload}
          disabled={!selectedFile || loading}
          aria-busy={loading}
        >
          {loading ? (
            <>
              <LoaderCircle
                size={17}
                className="upload-panel__spinner"
                aria-hidden="true"
              />
              Importing…
            </>
          ) : (
            <>
              Import dataset
              <span className="upload-panel__submit-icon" aria-hidden="true">
                <Upload size={15} />
              </span>
            </>
          )}
        </button>
      </footer>
    </section>
  );
}
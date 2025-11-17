;;; xml-lsp.el --- XML Language Server Protocol support -*- lexical-binding: t; -*-

;; Copyright © 2025 Google LLC.

;; Author: Dino Chiesa <dchiesa@google.com>
;; URL: https://github.com/SerdoSchofield/xml-lsp
;; Version: 0.2.0
;; Package-Requires: ((emacs "26.1") (lsp-mode "8.0") (eglot "1.0"))
;; Keywords: languages, xml, lsp

;; This file is not part of GNU Emacs.

;; Licensed under the Apache License, Version 2.0 (the "License");
;; you may not use this file except in compliance with the License.
;; You may obtain a copy of the License at
;;
;;     https://www.apache.org/licenses/LICENSE-2.0
;;
;; Unless required by applicable law or agreed to in writing, software
;; distributed under the License is distributed on an "AS IS" BASIS,
;; WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
;; See the License for the specific language governing permissions and
;; limitations under the License.

;;; Commentary:

;; This package provides Language Server Protocol (LSP) support for XML files
;; using the xml-lsp Python server. It supports both lsp-mode and eglot.
;;
;; The server provides:
;; - Schema-based validation (XSD 1.0 and 1.1)
;; - Completion suggestions for elements
;; - Diagnostic messages for validation errors
;;
;; Installation:
;;
;; 1. Install the xml-lsp Python server:
;;    git clone https://github.com/SerdoSchofield/xml-lsp
;;    cd xml-lsp
;;    python -m venv .venv
;;    source .venv/bin/activate  # or .venv\Scripts\activate on Windows
;;    pip install -r requirements.txt
;;
;; 2. Install this package and configure your schema locators:
;;
;; With Doom Emacs:
;;   Add to your packages.el:
;;     (package! xml-lsp :recipe (:host github :repo "SerdoSchofield/xml-lsp"))
;;
;;   Add to your config.el:
;;     (use-package! xml-lsp
;;       :config
;;       (setq xml-lsp-server-install-dir "~/xml-lsp")
;;       (setq xml-lsp-schema-locators
;;         '((:rootElement t
;;            :searchPaths ["/path/to/schema-dir"])
;;           (:locationHint "/path/to/schema-cache/schema_map.json")
;;           (:patterns [(:pattern "*.csproj"
;;                       :path "/path/to/Microsoft.Build.Core.xsd"
;;                       :useDefaultNamespace t)]))))
;;
;; With standard Emacs and lsp-mode:
;;   (require 'xml-lsp)
;;   (setq xml-lsp-server-install-dir "~/xml-lsp")
;;   (add-hook 'nxml-mode-hook #'xml-lsp-mode)
;;
;; With eglot:
;;   (require 'xml-lsp)
;;   (setq xml-lsp-server-install-dir "~/xml-lsp")
;;   (add-hook 'nxml-mode-hook #'xml-lsp-eglot-ensure)

;;; Code:

(require 'json)

(defgroup xml-lsp nil
  "XML Language Server Protocol support."
  :group 'languages
  :prefix "xml-lsp-")

(defcustom xml-lsp-server-install-dir nil
  "Directory where the xml-lsp server is installed.
This should be the root directory of the xml-lsp repository.
If nil, will try to locate it automatically."
  :type '(choice (const :tag "Auto-detect" nil)
                 (directory :tag "Installation directory"))
  :group 'xml-lsp)

(defcustom xml-lsp-schema-locators nil
  "Schema locator configuration for XML LSP.
This should be a list of schema locator specifications.

Each locator can be one of three types:

1. Root Element locator:
   (:rootElement t :searchPaths [\"/path/to/schemas\"])

2. Location Hint locator:
   (:locationHint \"/path/to/schema_map.json\")

3. Pattern-based locator:
   (:patterns [(:pattern \"*.csproj\"
                :path \"/path/to/schema.xsd\"
                :useDefaultNamespace t)])

Example:
  (setq xml-lsp-schema-locators
    \\='((:rootElement t
        :searchPaths [\"/home/user/schemas\"])
      (:locationHint \"/home/user/.xml-schemas/schema_map.json\")
      (:patterns [(:pattern \"*.csproj\"
                   :path \"/usr/share/schemas/Microsoft.Build.Core.xsd\"
                   :useDefaultNamespace t)])))"
  :type '(repeat sexp)
  :group 'xml-lsp)

(defcustom xml-lsp-log-file nil
  "Path to the log file for xml-lsp server.
If nil, logs will be written to /tmp/xmllsp.log."
  :type '(choice (const :tag "Default (/tmp/xmllsp.log)" nil)
                 (file :tag "Log file path"))
  :group 'xml-lsp)

(defcustom xml-lsp-log-level "INFO"
  "Logging level for xml-lsp server.
Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
  :type '(choice (const "DEBUG")
                 (const "INFO")
                 (const "WARNING")
                 (const "ERROR")
                 (const "CRITICAL"))
  :group 'xml-lsp)

(defun xml-lsp--find-server-install-dir ()
  "Find the xml-lsp server installation directory.
Returns the directory if found, nil otherwise."
  (or xml-lsp-server-install-dir
      ;; Try common locations
      (seq-find #'file-directory-p
                (list (expand-file-name "~/xml-lsp")
                      (expand-file-name "~/.local/share/xml-lsp")
                      (expand-file-name "~/.xml-lsp")))))

(defun xml-lsp--server-command ()
  "Return the command to start the xml-lsp server."
  (let* ((install-dir (xml-lsp--find-server-install-dir))
         (python-executable (if install-dir
                                (expand-file-name ".venv/bin/python" install-dir)
                              "python3"))
         (server-script (if install-dir
                            (expand-file-name "xml_language_server/xmllsp.py" install-dir)
                          "xmllsp.py")))
    (if (and install-dir
             (file-exists-p python-executable)
             (file-exists-p server-script))
        (append (list python-executable server-script)
                (when xml-lsp-log-file
                  (list "--log-file" xml-lsp-log-file))
                (when xml-lsp-log-level
                  (list "--log-level" xml-lsp-log-level)))
      (user-error "XML-LSP server not found. Please set `xml-lsp-server-install-dir' or install to ~/xml-lsp"))))

(defun xml-lsp--initialization-options ()
  "Generate initialization options for xml-lsp server."
  (when xml-lsp-schema-locators
    `(:schemaLocators ,(vconcat xml-lsp-schema-locators))))

;;; LSP-mode support

(defun xml-lsp-mode-setup ()
  "Set up xml-lsp with lsp-mode."
  (when (require 'lsp-mode nil t)
    (lsp-register-client
     (make-lsp-client
      :new-connection (lsp-stdio-connection #'xml-lsp--server-command)
      :major-modes '(nxml-mode xml-mode)
      :server-id 'xml-lsp
      :initialization-options #'xml-lsp--initialization-options))
    (add-to-list 'lsp-language-id-configuration '(nxml-mode . "xml"))
    (add-to-list 'lsp-language-id-configuration '(xml-mode . "xml"))))

;;;###autoload
(define-minor-mode xml-lsp-mode
  "Minor mode for xml-lsp support with lsp-mode."
  :lighter " XML-LSP"
  :group 'xml-lsp
  (if xml-lsp-mode
      (progn
        (xml-lsp-mode-setup)
        (when (and (require 'lsp-mode nil t)
                   (not (bound-and-true-p lsp-mode)))
          (lsp)))
    (when (and (require 'lsp-mode nil t)
               (bound-and-true-p lsp-mode))
      (lsp-disconnect))))

;;; Eglot support

(defun xml-lsp--eglot-initialization-options (_server)
  "Generate initialization options for eglot.
Argument _SERVER is ignored but required by eglot."
  (xml-lsp--initialization-options))

(defun xml-lsp-eglot-setup ()
  "Set up xml-lsp with eglot."
  (when (require 'eglot nil t)
    ;; Add xml-lsp to eglot server programs
    (add-to-list 'eglot-server-programs
                 `((nxml-mode xml-mode) . ,(xml-lsp--server-command)))
    
    ;; Register initialization options
    (with-eval-after-load 'eglot
      (defclass eglot-xml-lsp (eglot-lsp-server) ()
        "XML LSP server class for eglot.")
      
      (cl-defmethod eglot-initialization-options ((server eglot-xml-lsp))
        "Return initialization options for XML LSP server."
        (xml-lsp--eglot-initialization-options server)))))

;;;###autoload
(defun xml-lsp-eglot-ensure ()
  "Ensure eglot is running with xml-lsp for the current buffer."
  (interactive)
  (xml-lsp-eglot-setup)
  (when (require 'eglot nil t)
    (eglot-ensure)))

;;; Installation helpers

;;;###autoload
(defun xml-lsp-install ()
  "Install xml-lsp server.
Prompts for installation directory if not set."
  (interactive)
  (let* ((install-dir (or xml-lsp-server-install-dir
                          (read-directory-name "Install xml-lsp to: " "~/xml-lsp")))
         (default-directory install-dir))
    (unless (file-directory-p install-dir)
      (make-directory install-dir t))
    (message "Installing xml-lsp to %s..." install-dir)
    (unless (file-exists-p (expand-file-name "xml_language_server/xmllsp.py" install-dir))
      (user-error "Please git clone the repository to %s first" install-dir))
    (let ((venv-dir (expand-file-name ".venv" install-dir)))
      (unless (file-directory-p venv-dir)
        (message "Creating Python virtual environment...")
        (shell-command (format "cd %s && python3 -m venv .venv" (shell-quote-argument install-dir))))
      (message "Installing Python dependencies...")
      (let ((result (shell-command
                     (format "cd %s && %s -m pip install -r requirements.txt"
                             (shell-quote-argument install-dir)
                             (shell-quote-argument (expand-file-name ".venv/bin/python" install-dir))))))
        (if (eq result 0)
            (progn
              (setq xml-lsp-server-install-dir install-dir)
              (message "xml-lsp installed successfully!"))
          (error "Failed to install xml-lsp dependencies"))))))

;;;###autoload
(defun xml-lsp-version ()
  "Display xml-lsp server version."
  (interactive)
  (message "xml-lsp.el version 0.2.0"))

;; Setup hooks for auto-loading
;;;###autoload
(with-eval-after-load 'lsp-mode
  (xml-lsp-mode-setup))

;;;###autoload
(with-eval-after-load 'eglot
  (xml-lsp-eglot-setup))

(provide 'xml-lsp)

;;; xml-lsp.el ends here

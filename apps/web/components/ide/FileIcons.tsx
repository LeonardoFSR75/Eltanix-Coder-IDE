"use client";

import React from "react";

interface FileIconProps {
  filename: string;
  isFolder?: boolean;
  isOpen?: boolean;
  className?: string;
}

export function FileIcon({ filename, isFolder, isOpen, className = "" }: FileIconProps) {
  if (isFolder) {
    return (
      <svg
        className={`file-icon folder-icon ${isOpen ? "open" : ""} ${className}`}
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
        {isOpen && <path d="M2 10h20" />}
      </svg>
    );
  }

  const ext = filename.split(".").pop()?.toLowerCase() || "";
  const nameLower = filename.toLowerCase();

  // Python (.py)
  if (ext === "py") {
    return (
      <svg className={`file-icon py-icon ${className}`} width="15" height="15" viewBox="0 0 24 24">
        <path
          fill="#3776AB"
          d="M11.9 2c-5.1 0-4.8 2.2-4.8 2.2l.1 2.3h4.8v.7H5.2S2 6.8 2 11.9s2.8 4.9 2.8 4.9h1.7v-2.4c0-2.7 2.3-4.8 5-4.8h4.8V7.2s.3-5.2-4.4-5.2zm-2.6 1.6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"
        />
        <path
          fill="#FFD43B"
          d="M12.1 22c5.1 0 4.8-2.2 4.8-2.2l-.1-2.3h-4.8v-.7h6.8s3.2.4 3.2-4.7-2.8-4.9-2.8-4.9h-1.7v2.4c0 2.7-2.3 4.8-5 4.8h-4.8v2.4s-.3 5.2 4.4 5.2zm2.6-1.6a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"
        />
      </svg>
    );
  }

  // TypeScript / TSX
  if (ext === "ts" || ext === "tsx") {
    const isTsx = ext === "tsx";
    return (
      <span className={`file-icon-badge ts-badge ${isTsx ? "tsx" : ""} ${className}`}>
        {isTsx ? "TSX" : "TS"}
      </span>
    );
  }

  // JavaScript / JSX
  if (ext === "js" || ext === "jsx" || ext === "mjs") {
    const isJsx = ext === "jsx";
    return (
      <span className={`file-icon-badge js-badge ${isJsx ? "jsx" : ""} ${className}`}>
        {isJsx ? "JSX" : "JS"}
      </span>
    );
  }

  // JSON
  if (ext === "json") {
    return (
      <span className={`file-icon-badge json-badge ${className}`}>
        {"{}"}
      </span>
    );
  }

  // Markdown / MDX
  if (ext === "md" || ext === "mdx") {
    return (
      <svg className={`file-icon md-icon ${className}`} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" strokeWidth="2">
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M7 15V9l3 3 3-3v6" />
        <path d="M17 12l-2 3h4" />
      </svg>
    );
  }

  // CSS / SCSS / LESS
  if (ext === "css" || ext === "scss" || ext === "less") {
    return (
      <span className={`file-icon-badge css-badge ${className}`}>
        CSS
      </span>
    );
  }

  // HTML
  if (ext === "html") {
    return (
      <span className={`file-icon-badge html-badge ${className}`}>
        {"<>"}
      </span>
    );
  }

  // YAML / YML
  if (ext === "yaml" || ext === "yml") {
    return (
      <span className={`file-icon-badge yaml-badge ${className}`}>
        YML
      </span>
    );
  }

  // Dockerfile / .dockerignore
  if (nameLower.includes("docker")) {
    return (
      <svg className={`file-icon docker-icon ${className}`} width="15" height="15" viewBox="0 0 24 24" fill="#38BDF8">
        <path d="M13 10h2v2h-2v-2zm-3 0h2v2h-2v-2zm-3 0h2v2H7v-2zm-3 0h2v2H4v-2zm9-3h2v2h-2V7zm-3 0h2v2h-2V7zm-3 0h2v2H7V7zm6-3h2v2h-2V4zm-1.8 14.5c-1.3.8-3.1 1-4.7.7-1.7-.3-3.1-1.3-4-2.7l-.4.3c1.1 1.6 2.7 2.7 4.6 3.1 1.9.4 4 .1 5.6-.8l-1.1-.6z" />
      </svg>
    );
  }

  // Shell / Bash (.sh, .bash, zsh)
  if (ext === "sh" || ext === "bash" || ext === "zsh") {
    return (
      <span className={`file-icon-badge sh-badge ${className}`}>
        {">_"}
      </span>
    );
  }

  // Default File
  return (
    <svg
      className={`file-icon default-icon ${className}`}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

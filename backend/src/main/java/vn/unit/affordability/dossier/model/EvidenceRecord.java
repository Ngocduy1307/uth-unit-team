package vn.unit.affordability.dossier.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.time.OffsetDateTime;

@Entity
@Table(name = "evidence_records")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EvidenceRecord {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "file_name", length = 255, nullable = false)
    private String fileName;

    @Column(name = "file_hash", length = 64, nullable = false)
    private String fileHash;

    @Column(name = "file_type", length = 32, nullable = false)
    private String fileType;

    @Column(name = "storage_path", length = 512, nullable = false)
    private String storagePath;

    @Column(name = "status", length = 32, nullable = false)
    @Builder.Default
    private String status = "RECEIVED";

    @Column(name = "uploaded_by", length = 64, nullable = false)
    private String uploadedBy;

    @Column(name = "file_size_bytes")
    private Long fileSizeBytes;

    @Column(name = "mime_type", length = 128)
    private String mimeType;

    @Column(name = "ocr_status", length = 32)
    @Builder.Default
    private String ocrStatus = "PENDING";

    @Column(name = "ocr_processed_at")
    private OffsetDateTime ocrProcessedAt;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;
}

package vn.unit.affordability.dossier.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class EvidenceRecordResponse {

    private String id;
    private String dossierId;
    private String fileName;
    private String fileHash;
    private String fileType;
    private String storagePath;
    private String status;
    private String uploadedBy;
    private Long fileSizeBytes;
    private String mimeType;
    private String ocrStatus;
    private OffsetDateTime ocrProcessedAt;
    private Integer version;
    private Boolean isLatest;
    private String updatedBy;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}

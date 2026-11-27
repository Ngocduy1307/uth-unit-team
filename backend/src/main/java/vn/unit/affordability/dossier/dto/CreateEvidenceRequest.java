package vn.unit.affordability.dossier.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class CreateEvidenceRequest {

    @NotBlank
    @Size(max = 255)
    private String fileName;

    @NotBlank
    @Pattern(regexp = "^[a-fA-F0-9]{64}$", message = "fileHash must be a valid 64-character SHA-256 hex string")
    private String fileHash;

    @NotBlank
    @Pattern(
        regexp = "^(BANK_STATEMENT|SALARY_CONFIRMATION|LABOR_CONTRACT|ID_CARD|CIC_REPORT|OTHER)$",
        message = "fileType must be one of BANK_STATEMENT, SALARY_CONFIRMATION, LABOR_CONTRACT, ID_CARD, CIC_REPORT, OTHER"
    )
    private String fileType;

    @NotBlank
    @Size(max = 512)
    private String storagePath;

    @NotBlank
    @Size(max = 64)
    private String uploadedBy;

    @NotNull
    @Min(1)
    private Long fileSizeBytes;

    @NotBlank
    @Size(max = 128)
    private String mimeType;

    @Size(max = 500)
    private String reason;
}

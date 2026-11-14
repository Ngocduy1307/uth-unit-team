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
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDate;
import java.time.OffsetDateTime;

@Entity
@Table(name = "dossiers")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Dossier {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "application_id", length = 64, nullable = false, unique = true)
    private String applicationId;

    @Column(name = "applicant_id", length = 64, nullable = false)
    private String applicantId;

    @Column(name = "applicant_name", length = 255, nullable = false)
    private String applicantName;

    @Column(name = "bank_code", length = 32, nullable = false)
    private String bankCode;

    @Column(name = "status", length = 32, nullable = false)
    @Builder.Default
    private String status = "DRAFT";

    @Column(name = "maker_id", length = 64)
    private String makerId;

    @Column(name = "checker_id", length = 64)
    private String checkerId;

    @Column(name = "analysis_date")
    private LocalDate analysisDate;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}


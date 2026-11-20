package vn.unit.affordability.financial.model;

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

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Entity
@Table(name = "obligations")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Obligation {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "institution_name", length = 255, nullable = false)
    private String institutionName;

    @Column(name = "obligation_type", length = 32, nullable = false)
    private String obligationType;

    @Column(name = "monthly_payment", precision = 18, scale = 2, nullable = false)
    private BigDecimal monthlyPayment;

    @Column(name = "total_balance", precision = 18, scale = 2, nullable = false)
    @Builder.Default
    private BigDecimal totalBalance = BigDecimal.ZERO;

    @Column(name = "remaining_tenor_months")
    private Integer remainingTenorMonths;

    @Column(name = "interest_rate", precision = 5, scale = 2)
    private BigDecimal interestRate;

    @Column(name = "source", length = 32, nullable = false)
    @Builder.Default
    private String source = "DECLARED";

    @Column(name = "is_duplicated", nullable = false)
    @Builder.Default
    private Boolean isDuplicated = false;

    @Column(name = "is_included_in_dti", nullable = false)
    @Builder.Default
    private Boolean isIncludedInDti = true;

    @Column(name = "notes", columnDefinition = "TEXT")
    private String notes;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;
}

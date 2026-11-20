package vn.unit.affordability.financial.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Entity
@Table(
    name = "affordability_snapshots",
    uniqueConstraints = {
        @UniqueConstraint(
            name = "uq_snapshots_dossier_version",
            columnNames = {"dossier_id", "snapshot_version"}
        )
    }
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AffordabilitySnapshot {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "snapshot_version", nullable = false)
    @Builder.Default
    private Integer snapshotVersion = 1;

    @Column(name = "formula_version", length = 32, nullable = false)
    @Builder.Default
    private String formulaVersion = "V1";

    @Column(name = "eligible_net_income", precision = 18, scale = 2, nullable = false)
    private BigDecimal eligibleNetIncome;

    @Column(name = "declared_living_expenses", precision = 18, scale = 2, nullable = false)
    private BigDecimal declaredLivingExpenses;

    @Column(name = "floor_living_expenses", precision = 18, scale = 2, nullable = false)
    private BigDecimal floorLivingExpenses;

    @Column(name = "effective_living_expenses", precision = 18, scale = 2, nullable = false)
    private BigDecimal effectiveLivingExpenses;

    @Column(name = "existing_debt_service", precision = 18, scale = 2, nullable = false)
    private BigDecimal existingDebtService;

    @Column(name = "proposed_loan_amount", precision = 18, scale = 2, nullable = false)
    private BigDecimal proposedLoanAmount;

    @Column(name = "proposed_loan_tenor_months", nullable = false)
    private Integer proposedLoanTenorMonths;

    @Column(name = "proposed_interest_rate", precision = 5, scale = 2, nullable = false)
    private BigDecimal proposedInterestRate;

    @Column(name = "proposed_loan_payment", precision = 18, scale = 2, nullable = false)
    private BigDecimal proposedLoanPayment;

    @Column(name = "baseline_residual", precision = 18, scale = 2, nullable = false)
    private BigDecimal baselineResidual;

    @Column(name = "baseline_dti", precision = 5, scale = 4, nullable = false)
    private BigDecimal baselineDti;

    @Column(name = "stress1_residual", precision = 18, scale = 2, nullable = false)
    private BigDecimal stress1Residual;

    @Column(name = "stress1_dti", precision = 5, scale = 4, nullable = false)
    private BigDecimal stress1Dti;

    @Column(name = "stress2_residual", precision = 18, scale = 2, nullable = false)
    private BigDecimal stress2Residual;

    @Column(name = "stress2_dti", precision = 5, scale = 4, nullable = false)
    private BigDecimal stress2Dti;

    @Column(name = "max_dti_limit", precision = 5, scale = 4, nullable = false)
    @Builder.Default
    private BigDecimal maxDtiLimit = new BigDecimal("0.5000");

    @Column(name = "min_residual_limit", precision = 18, scale = 2, nullable = false)
    @Builder.Default
    private BigDecimal minResidualLimit = new BigDecimal("5000000.00");

    @Column(name = "policy_status", length = 32, nullable = false)
    private String policyStatus;

    @Column(name = "policy_notes", columnDefinition = "TEXT")
    private String policyNotes;

    @Column(name = "calculated_by", length = 64, nullable = false)
    private String calculatedBy;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;
}
